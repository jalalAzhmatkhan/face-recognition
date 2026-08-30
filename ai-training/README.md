# ai-training

Face Recognition Access Control — training pipeline (TR-01 scaffold, TR-02/TR-03 QC + embedding worker).

Stages: data (S3 snapshot manifests) → preprocessing (frames, pose bins, EDA) → embedding (AdaFace, gallery upsert) → training (fine-tune + MLflow) → evaluation (Recall → F1 → Precision + latency ms).

## Run

```bash
uv sync                 # base deps: pydantic, numpy, celery, redis, psycopg, pgvector
uv run pytest           # unit tests (no real Postgres/Redis/cv2/mediapipe needed)
uv run ruff check .
uv run ai-training --help
```

Heavy vision/ML deps (torch, mlflow, boto3, opencv-python-headless, mediapipe) are an optional extra — all imports are lazy:

```bash
uv sync --extra ml
```

**Why the split**: TR-02's quality metrics (blur/brightness/face-size) and TR-03's alignment math are plain-numpy, dependency-light, and unit-tested directly. Video decode (`cv2.VideoCapture`) and face-landmark detection (`mediapipe`) genuinely need the heavy `ml` extra, so those code paths are lazily imported and exercised only via manual verification against a real recording, not automated tests. `celery`/`redis`/`psycopg[binary]`/`pgvector` are base deps (not `ml`) because they're needed to unit-test the worker's idempotency logic (with a mocked DB cursor) without pulling in torch/mediapipe.

## Configuration

Env vars with prefix `TRN_`, nested with `__` (see `src/ai_training/config.py`):
`TRN_S3__BUCKET`, `TRN_MLFLOW__TRACKING_URI`, `TRN_DB__DSN`, `TRN_TRAINING__DEVICE`,
`TRN_QC__BLUR_VARIANCE_MIN`, `TRN_EMBEDDER__BACKEND`, `TRN_REDIS_URL`, …
No credentials in code; AWS uses the standard credential chain.

## Rules

- Media never rests on local disk (in-memory/tmpfs streaming only, NFR-SEC-02). The one documented exception is `ai_training/quality/pipeline.py::extract_frames`, which writes the enrollment video to a short-lived OS temp file because `cv2.VideoCapture` cannot decode from an in-memory buffer — the file is deleted in a `finally` block even if decoding raises.
- Metric priority: Recall → F1 → Precision, plus latency in ms.

## TR-02: Quality Check (`ai_training/quality/`)

Real implementation (not a stub):

- `metrics.py` — blur (variance of Laplacian, pure numpy), brightness (mean pixel), face-size ratio.
- `pose.py` — **ASM-03 corrected 2026-08-30**: the enrollment video is a *head-orientation* sweep (yaw+pitch only, body/camera fixed), not a body/camera rotation — there is no back-of-head segment. This module maps the 12 clock positions to (yaw, pitch) targets on a circle (`yaw_range_deg`/`pitch_range_deg`, default ±35°/±25°, tunable via `TRN_QC__YAW_RANGE_DEG`/`TRN_QC__PITCH_RANGE_DEG`) and estimates a frame's actual (yaw, pitch) via `cv2.solvePnP` against a generic 3D face model, from landmarks detected with MediaPipe's `face_mesh` (model assets bundled in the pip wheel — no separate download, unlike SCRFD/AdaFace/MiniFASNet).
- `pipeline.py` — decodes the video (short-lived temp file, see above), evaluates every sampled frame, and produces a `QCReport` (`report.py`): per-clock-position pass/fail + reasons (`blurry`, `bad_lighting`, `face_too_small`, `pose_out_of_range`, `no_face_detected`), a `coverage_ratio`, and an overall `PASS`/`REJECTED_QUALITY` decision (`coverage_ratio >= QCSettings.min_pass_ratio`, default 75% of the 12 positions).

**Library choice**: `mediapipe` (legacy `solutions.face_mesh`/bundled model assets) + `opencv-python-headless` (video decode + `solvePnP`), NOT OpenCV's YuNet DNN detector or InsightFace/SCRFD — those require downloading a separate pretrained weight file, which this task is explicitly not allowed to do (procurement decision pending, see `documentation/research/recommendations.md`). Haar cascades (also bundled in `opencv-python`) were considered but rejected: they give bounding boxes only, no landmarks, so `solvePnP`-based pose estimation would not be possible.

## TR-03: Embedding Extraction (`ai_training/embedding/`)

Real plumbing, placeholder embedder:

- `sampling.py` — picks the best K frames per pose bucket by blur score (real logic).
- `alignment.py` — Umeyama similarity-transform (pure numpy, unit-tested) + `cv2.warpAffine` crop to the standard ArcFace/AdaFace 112×112 template (real logic, future-proofed for AdaFace).
- `embedder.py` — `EmbedderInterface` abstraction (same shape as `ai-inference/src/ai_inference/models/loader.py`'s `ModelLoader`): `StubEmbedder` (deterministic, hash-seeded, L2-normalized — **explicitly NOT real face recognition**) is the only usable backend today; `AdaFaceEmbedder` is a documented `NotImplementedError` skeleton blocked on procuring AdaFace weights.
- `extractor.py` — orchestrates sampling → alignment → embed → per-pose-bucket mean-normalized template (recommendations.md §4).

## Worker (`ai_training/worker/`) — wiring into Celery

`backend/app/worker/tasks.py` has a stub `run_enrollment_qc` (BE-07) whose docstring says "TR-02 will replace this function's body". Since `ai-training` is a separate Python project (own venv/pyproject, cannot import `backend/`'s code or vice versa), that replacement happens as **a second Celery app registering a task under the identical name**, not an edit to backend's file:

```
ai_training/worker/celery_app.py   # new Celery app "ai_training_worker", broker/backend = TRN_REDIS_URL
ai_training/worker/tasks.py        # run_enrollment_qc, registered as name="app.worker.tasks.run_enrollment_qc"
```

Celery dispatches purely by task name + queue, not by which codebase defines it — so when backend's `app/services/qc_queue.py` calls `run_enrollment_qc.delay(session_id)`, whichever worker process is actually subscribed to `frac_default` and has that name registered executes it. Both `task_default_queue` here and `TRN_REDIS_URL` MUST match backend's `app/worker/celery_app.py` (`task_default_queue="frac_default"`) and `REDIS_URL` respectively — there is no automatic sharing between the two projects' env namespaces.

**Running the two workers side-by-side without collision**:

```bash
# backend/ (existing BE-07 worker) — after this task lands, STOP running
# backend's worker for run_enrollment_qc in any environment where
# ai-training's worker also runs, or whichever process grabs a given job
# first wins non-deterministically. In dev, simplest is to only run:
cd ai-training
TRN_REDIS_URL=redis://localhost:6379/0 TRN_DB__DSN=postgresql://... uv run celery -A ai_training.worker.celery_app worker --loglevel=info
```

If you need backend's worker running too (e.g. for `revoke_enrollment_cleanup`, which this task does NOT touch), have it consume a DIFFERENT queue than ai-training's `run_enrollment_qc`, or simply don't run backend's own `run_enrollment_qc` task registration in that environment (it's still defined in `backend/app/worker/tasks.py` — this task did not touch `backend/` at all, per its scope restriction — but nothing dispatches to it once ai-training's worker is the one consuming `frac_default`).

**Idempotency approach** (ai-training cannot import `backend/app/services/enrollment_state_machine.py`): rather than re-implementing the whole state machine, every write goes through a "guarded UPDATE" (`ai_training/db/enrollment_repo.py::guarded_transition`) whose `WHERE id = ... AND state = expected_state` clause both performs and verifies the transition atomically — 0 rows affected means a duplicate/racing job already saw this session move on, and is treated as a no-op (audited as `job.qc_skipped`), never an error. `run_enrollment_qc_core` (the DB-cursor-injected core, testable without Celery/Postgres) checks state first-thing before doing any work, exactly mirroring backend's own `_run_enrollment_qc_stub` idiom.

**Retry / dead-letter**: same shape as `backend/app/worker/tasks.py::DeadLetterTask` — `autoretry_for=(ConnectionError, TimeoutError, OSError)` with exponential backoff + jitter, `max_retries=5`; on final failure, `on_failure` writes one `audit_logs` row with `action="job.dead_letter"` via raw SQL (can't import backend's `AuditLogRepository`).

### KNOWN GAP — DB role permissions (needs manual resolution)

`backend/README.md` documents two Postgres roles for ai-training: `ai_training_ro` (SELECT-only on business tables, no `face_embeddings`/`audit_logs` access) and `ai_training_embeddings_write` (SELECT/INSERT/UPDATE on `face_embeddings` ONLY). **Neither role currently grants** the `UPDATE enrollment_sessions` (state/qc_report) or `INSERT audit_logs` this worker needs to perform FR-ENR-06/07's state transitions and audit trail. This task did not run any migration (out of scope), so `ai_training/config.py::DBSettings` uses a single configurable `dsn` and the gap is documented here rather than silently worked around. **Before running this against a real database**, either:

1. widen `ai_training_embeddings_write`'s grants (new backend migration, out of scope here) to also cover `UPDATE enrollment_sessions (state, qc_report, updated_at)` and `INSERT audit_logs`, or
2. point `TRN_DB__DSN` at a role with those grants for now (e.g. the same role `backend/` itself uses) as a stop-gap, and narrow it later.

## Manual verification checklist (Postgres + Redis required — WSL Docker)

Automated tests never touch real Postgres/Redis (per task instructions) — please verify manually:

1. `docker compose -f ../docker-compose.dev.yml up postgres redis` (from repo root) with the BE-02 migrations already applied (`cd backend && uv run alembic upgrade head`).
2. Resolve the DB-role gap above (grant the extra permissions, or use a stop-gap DSN).
3. `cd ai-training && uv sync --extra ml` (installs opencv-python-headless/mediapipe/torch/mlflow/boto3 — mediapipe is a sizeable wheel, expect it to take a while).
4. Set env: `TRN_DB__DSN=postgresql://...`, `TRN_REDIS_URL=redis://localhost:6379/0`, `TRN_S3__BUCKET=...` (or point at a MinIO/localstack endpoint via `TRN_S3__ENDPOINT_URL`).
5. Start the worker: `uv run celery -A ai_training.worker.celery_app worker --loglevel=info`.
6. Create a real enrollment session through `backend/`'s API up through `CAPTURED`/`QC_RUNNING` (per FR-ENR-05/06 flow) with an actual short webcam recording uploaded as the video media object.
7. Confirm: `run_enrollment_qc.delay(session_id)` (dispatched by backend's `qc_queue.py`) is picked up by THIS worker (check its logs, not backend's), `enrollment_sessions.state`/`qc_report` update as expected, `face_embeddings` rows appear for `PASS`ed sessions (`model_version = 'stub-v1'`, one row per covered pose bucket), and `audit_logs` gains `enrollment.qc_passed`/`enrollment.qc_rejected`/`enrollment.embedding_completed` rows.
8. Verify idempotency for real: call `run_enrollment_qc.delay(session_id)` a second time for an already-`ENROLLED` session and confirm it no-ops (one more `job.qc_skipped` audit row, no state change, no duplicate `face_embeddings`).
9. Verify no worker "collision": confirm backend's own `run_enrollment_qc` stub body (in `backend/app/worker/tasks.py`) never actually executes once ai-training's worker is the one consuming `frac_default` (no `job.qc_stub_executed` audit rows appear for new sessions).
10. Tune `TRN_QC__*` thresholds against real capture footage — current defaults (`blur_variance_min=80`, `brightness` 40–215, `face_ratio_min=0.12`, `pose_tolerance_deg=15`, `yaw_range_deg=35`, `pitch_range_deg=25`, `min_pass_ratio=0.75`) are placeholders, not calibrated against real recordings.
