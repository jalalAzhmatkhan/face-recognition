# ai-inference

Face Recognition Access Control — inference service (IN-01 scaffold).

Pipeline (per ratified research, with the MediaPipe substitution for SCRFD made project-wide since TR-02 -- see `src/ai_inference/models/loader.py` module docstring): MediaPipe Face Landmarker detection → alignment → liveness (placeholder until IN-04) → AdaFace embedding → gallery matching → decision.

## Run

```bash
uv sync                 # light deps only (FastAPI, prometheus-client, ...)
uv run pytest           # smoke tests
uv run ruff check .
uv run uvicorn ai_inference.main:app --port 8100
```

Heavy ML deps (torch, mlflow, onnxruntime, **and the `ai-training` path dependency** — pulls in `ai-training[ml]`'s own torch/opencv-python-headless/mediapipe/psycopg[binary]/pgvector/boto3/gdown transitively) are an optional extra — all imports are lazy:

```bash
uv sync --extra ml
```

`ai-inference` deliberately does NOT duplicate detection/alignment/embedding
code (IN-03 decision): it depends on the already-live `ai_training.embedding.*`
/ `ai_training.quality.pose` code via a `uv` **path dependency**
(`[tool.uv.sources]` in `pyproject.toml`, `../ai-training`, editable) rather
than vendoring or reimplementing it. See `src/ai_inference/training_bridge.py`
for how `ai_inference.config.Settings` (`INF_*`) hands off to
`ai_training.config.Settings` (`TRN_*`) for the embedder specifically.

## Endpoints

- `GET /healthz` — status + loaded model versions
- `GET /metrics` — Prometheus (per-stage latency histograms, decision counters)
- `POST /recognize` — face recognition over 1+ base64 JPEG/PNG frames (IN-03).
  **No device authentication yet (IN-02 gap)** — see the endpoint's docstring
  in `src/ai_inference/main.py` and `src/ai_inference/pipeline/recognize.py`'s
  module docstring for the full list of deliberate gaps (liveness placeholder
  pending IN-04, no `POST /access-events` emission pending IN-06, no atomic
  model/gallery switch pending IN-07, `SPOOF_SUSPECTED` never produced).

  Request: `{"frames_base64": ["<base64 jpeg/png>", ...]}` (>=1 frame; multi-frame
  temporal voting per recommendations.md §5 — a user must win >= `INF_MIN_FRAMES_FOR_GRANT`
  frames to be `GRANTED`).

  Response: `{"decision": "GRANTED"|"UNKNOWN", "user_id": "...", "similarity": 0.0,
  "liveness_score": 1.0, "model_version": "...", "latency_ms": 0}`.

## Configuration

Env vars with prefix `INF_` (see `src/ai_inference/config.py`):

- `INF_MLFLOW_TRACKING_URI`, `INF_MODEL_LOADER=stub|mlflow|adaface` (`mlflow`/`adaface`
  are aliases for the same real loader — see `models/loader.py`'s "Naming/honesty
  note"), `INF_MODEL_STAGE_OR_VERSION`.
- `INF_DB_DSN` — Postgres DSN using the read-only `ai_inference_ro` role
  (backend migration `b7c4e1a2d9f0`; SELECT-only on `models`/`face_embeddings`,
  see `backend/README.md`), required for `/recognize`.
- `INF_ANN_TOP_K` (default 50), `INF_SIMILARITY_THRESHOLD` (default 0.35),
  `INF_MARGIN_THRESHOLD` (default 0.0), `INF_MIN_FRAMES_FOR_GRANT` (default 2).
- To point the embedder at a specific AdaFace checkpoint/arch, set the SAME
  `TRN_EMBEDDER__ADAFACE_ARCH` / `TRN_EMBEDDER__ADAFACE_WEIGHTS_PATH` env vars
  used by `ai-training` itself (see `training_bridge.py`) — no separate
  `INF_*` knobs are invented for this.

No credentials in code.

## Observability (XC-04)

- **Metrics**: `GET /metrics` (see above) — already existed from IN-01, per-stage latency histograms live in `src/ai_inference/metrics.py`.
- **Tracing (opsional/lazy)**: OTel, off by default. `uv sync --extra otel` + set `OTEL_EXPORTER_OTLP_ENDPOINT` (e.g. `http://localhost:4317`) to enable; otherwise `setup_tracing()` in `src/ai_inference/tracing.py` is a no-op so the service stays runnable in dev/CI without a collector.
