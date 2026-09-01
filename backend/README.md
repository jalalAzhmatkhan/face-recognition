# backend — Core API

FastAPI + Pydantic v2, dimanage dengan [`uv`](https://docs.astral.sh/uv/). Python ≥ 3.12.

## Layering

```
app/
  routers/        # HTTP layer (FastAPI routers) — deny-by-default auth deps mulai BE-03
  dependencies/   # FastAPI DI: auth/RBAC (`get_current_staff`, `require_role`) — BE-03
  services/       # Business logic / orchestration (mis. `auth_service.py`, BE-03)
  schemas/        # Pydantic request/response contracts, terpisah dari ORM models — BE-03
  repositories/   # Data access — query helpers atas app/models (BE-02: contoh `users.py`)
  models/         # SQLAlchemy 2.x ORM models, satu module per tabel TSD §4 (BE-02)
  db/             # engine/session (BE-02)
  core/           # config (pydantic-settings), structured logging, RFC 9457 errors, JWT+hashing (`security.py`, BE-03)
  worker/         # Celery app + tasks — retry/idempotency/dead-letter infra (BE-07)
  cli.py          # perintah ops satu-kali tanpa endpoint HTTP (mis. `create_admin`, BE-03)
migrations/       # alembic (BE-02, BE-03)
tests/            # pytest
```

## Menjalankan

```bash
uv sync                                   # install deps (buat .venv)
uv run uvicorn app.main:app --reload      # http://localhost:8000/healthz
uv run pytest                             # test
uv run ruff check .                       # lint
```

## Database & migrasi (BE-02)

Skema (SQLAlchemy 2.x models di `app/models/`, satu file per tabel TSD §4) + alembic
migration baseline yang membuat SEMUA tabel, extension `pgvector`, index HNSW
(cosine) pada `face_embeddings.vector`, tabel `access_events` sebagai native
Postgres partitioned table (RANGE by month on `occurred_at`), dan role DB
terpisah untuk `ai-training`.

```
app/db/
  base.py       # DeclarativeBase
  session.py    # engine/sessionmaker (lazy, DATABASE_URL dari Settings)
app/models/     # satu module per tabel + enums.py (state machine, status, dst)
app/repositories/
  users.py      # contoh pola repo (get/list) — CRUD lengkap menyusul di BE-04+
migrations/
  env.py        # terhubung ke Settings.database_url, target_metadata = app.models.Base.metadata
  versions/
    f5f1daa8bc61_baseline_schema.py   # semua tabel + extension + HNSW + partisi
    3a5b0a58f7ab_db_role_separation.py  # role ai_training_ro + ai_training_embeddings_write
```

### Menjalankan migrasi

Butuh Postgres 16 dengan extension `vector` terinstal (image `pgvector/pgvector`,
lihat `docker-compose.dev.yml` di root repo). Set `DATABASE_URL` di `.env`
(format `postgresql+psycopg://user:pass@host:5432/db`), lalu:

```bash
docker compose -f ../docker-compose.dev.yml up postgres   # dari root repo
uv run alembic upgrade head                                # jalankan migrasi
uv run alembic downgrade -1                                 # rollback satu step
uv run alembic upgrade head --sql                           # dry-run, cetak SQL saja (tanpa koneksi DB)
```

> **Keterbatasan lingkungan pengembangan agent ini**: tidak ada Postgres+pgvector
> yang live, jadi `alembic upgrade head` belum pernah dijalankan terhadap
> database sungguhan di sini. Yang sudah diverifikasi tanpa koneksi DB nyata:
> import semua model (skema `Base.metadata` terbentuk tanpa error) dan
> `alembic upgrade head --sql` / `alembic downgrade head:base --sql` (dry-run,
> merender seluruh SQL migrasi termasuk `CREATE EXTENSION vector`, index HNSW,
> partisi, dan grants role) tanpa error — lihat `tests/test_db_schema.py`.
> **Yang WAJIB diverifikasi manual oleh siapa pun yang punya Postgres+pgvector
> jalan** sebelum menganggap BE-02 selesai secara penuh:
> - `uv run alembic upgrade head` benar-benar sukses end-to-end pada Postgres 16 + pgvector,
> - index HNSW benar-benar terbentuk (`\d face_embeddings` di psql),
> - insert ke `access_events` ter-route ke partisi yang benar (dan ke `access_events_default` di luar range),
> - `uv run alembic downgrade base` bersih (roundtrip drop semua tabel/enum/extension),
> - role `ai_training_ro`/`ai_training_embeddings_write` benar-benar membatasi akses (lihat di bawah).

### Access-events partitions

`access_events` dipartisi per bulan (native Postgres `PARTITION BY RANGE
(occurred_at)`). Migration baseline membuat 2 partisi contoh
(`access_events_2026_08`, `access_events_2026_09`) plus satu partisi
`DEFAULT` (`access_events_default`) sebagai jaring pengaman untuk timestamp di
luar range yang sudah dibuat. Menambah partisi bulan berikutnya (manual untuk
sekarang — otomasi penuh ada di task lain, mis. BE-14):

```sql
CREATE TABLE access_events_2026_10 PARTITION OF access_events
  FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');
```

Buat migration alembic baru (`uv run alembic revision -m "access_events partition YYYY_MM"`)
berisi `op.execute(...)` dengan SQL di atas — jangan menaruh pembuatan partisi baru di
migration baseline yang sudah ada.

### DB role separation (ai-training read-only + embeddings-write)

Sesuai TSD §4/§6 ("ai-training gets read-only + embeddings-write role";
"restrict embedding read access"), migration `3a5b0a58f7ab` membuat dua role
Postgres `NOLOGIN` (tanpa password — kredensial login diberikan terpisah oleh
DBA/secret manager, tidak pernah lewat migration):

- **`ai_training_ro`** — `SELECT` saja pada tabel bisnis (`users`,
  `staff_accounts`, `consents`, `enrollment_sessions`, `media_objects`,
  `models`, `devices`, `access_policies`, `access_events`). **Tidak** punya akses
  ke `face_embeddings` (risiko embedding-inversion) atau `audit_logs`.
- **`ai_training_embeddings_write`** — `SELECT, INSERT, UPDATE` HANYA pada
  `face_embeddings` (untuk upsert gallery setelah training, FR-ENR-07/TR-03).
  Tidak ada akses ke tabel lain.

`audit_logs` juga di-*revoke* `UPDATE, DELETE` dari `PUBLIC` di migration yang
sama, supaya append-only (NFR-SEC-05) ditegakkan di level DB, bukan cuma
disiplin di kode aplikasi/repository.

Cara `ai-training` memakainya (di service `ai-training/`, task terpisah):

```bash
# Setelah DBA memberi password/login ke role ini:
DATABASE_URL_RO=postgresql+psycopg://ai_training_ro:<pwd>@host:5432/frac
DATABASE_URL_EMBEDDINGS_WRITE=postgresql+psycopg://ai_training_embeddings_write:<pwd>@host:5432/frac
```

Gunakan `DATABASE_URL_RO` untuk query dataset (tanpa risiko baca embeddings),
dan `DATABASE_URL_EMBEDDINGS_WRITE` khusus untuk job yang meng-upsert
`face_embeddings`. JANGAN memberi role ini `LOGIN`/password lewat migration —

### DB role: `ai_inference_ro` (ai-inference, read-only, IN-03)

Migration `b7c4e1a2d9f0` membuat role Postgres `NOLOGIN` ketiga,
`ai_inference_ro`, khusus untuk service `ai-inference/`'s `/recognize` ANN
gallery search. Jauh lebih sempit daripada `ai_training_ro`: HANYA `SELECT`
pada dua tabel —

- **`models`** — untuk menentukan versi mana yang `stage='PRODUCTION'` saat ini.
- **`face_embeddings`** — untuk pgvector top-k search (`vector <=> ...`) pada
  versi PRODUCTION tersebut.

Tidak ada akses ke `users`/`staff_accounts`/`audit_logs`/tabel lain sama
sekali (least privilege, TSD §6). Sama seperti role lain di atas, kredensial
login diberikan terpisah oleh DBA/secret manager, tidak pernah lewat
migration:

```bash
DATABASE_URL_AI_INFERENCE_RO=postgresql://ai_inference_ro:<pwd>@host:5432/frac
```

Service `ai-inference/` memakainya lewat `INF_DB_DSN` (lihat
`ai-inference/src/ai_inference/config.py` dan `ai_inference/gallery.py`).


itu harus lewat mekanisme secret yang sama dengan kredensial lain (NFR-OPS-03).

## AuthN/AuthZ staff (BE-03)

Login staff (console web) memakai **JWT lokal berbasis email+password** terhadap
tabel `staff_accounts`, bukan OIDC eksternal — TSD §6 hanya menyebut "staff OIDC +
RBAC" tanpa memilih IdP konkret, jadi fase ini mengimplementasikan jalur password
sebagai v1. Kolom `oidc_sub` tetap ada di skema (sekarang nullable, lihat migration
`48b08e41d49a`) sebagai penyiapan federasi OIDC eksternal di fase mendatang — belum
dipakai oleh kode ini.

**Pilihan library** (didokumentasikan sesuai keputusan teknis task):
- **Password hashing: `argon2-cffi`** (Argon2id) — direkomendasikan OWASP saat ini,
  tidak punya batas 72-byte seperti bcrypt, dan menghindari masalah kompatibilitas
  versi `passlib`+`bcrypt`. Dipakai langsung (bukan lewat `passlib`) di
  `app/core/security.py`.
- **JWT: `PyJWT`** — API lebih sederhana dan lebih aktif dimaintain dibanding
  `python-jose` untuk kebutuhan HS256 saja. Signing key dari `Settings.jwt_secret_key`
  (env `JWT_SECRET_KEY`, **wajib** diganti per-lingkungan; placeholder di
  `.env.example` bukan untuk dipakai di luar dev lokal).

**Endpoint** (`app/routers/auth.py`, mount di `{API_V1_PREFIX}/auth`):

| Method & path | Body | Response | Catatan |
|---|---|---|---|
| `POST /auth/login` | `{email, password}` | 200 `{access_token, refresh_token, token_type, expires_in}` | 401 problem+json generik pada kredensial invalid — akun tidak ada vs password salah menghasilkan response identik (NFR-SEC-04, no user enumeration) |
| `POST /auth/refresh` | `{refresh_token}` | 200 `{access_token, token_type, expires_in}` | 401 pada token invalid/expired/salah tipe/akun sudah tidak ada. Rotasi minimal: refresh token TIDAK dirotasi (tetap valid sampai expiry-nya sendiri), hanya access token baru yang diterbitkan |
| `GET /auth/me` | — (Bearer token) | 200 `{id, email, role}` | Contoh endpoint terproteksi (`get_current_staff`, role apa saja) |
| `GET /auth/admin-only-example` | — (Bearer token) | 200/403 | Contoh RBAC (`require_role(StaffRole.ADMIN)`) — endpoint dummy untuk membuktikan pola, bukan endpoint bisnis |

Access token default 15 menit, refresh token default 7 hari — konfigurable via
`ACCESS_TOKEN_EXPIRE_MINUTES` / `REFRESH_TOKEN_EXPIRE_MINUTES`.

**RBAC deny-by-default**: `app/dependencies/auth.py` menyediakan `get_current_staff`
(401 jika token tidak ada/invalid/expired) dan `require_role(*roles)` (403 jika role
staff tidak termasuk yang diizinkan; SELALU resolve `get_current_staff` dulu, jadi
token invalid tetap 401 bukan 403). Tidak ada middleware global yang memberi akses —
setiap router bisnis baru (BE-04 dst.) WAJIB memasang salah satu dependency ini
secara eksplisit per-endpoint; endpoint yang lupa memasangnya otomatis terbuka tanpa
auth, jadi ini harus jadi bagian dari code review checklist.

**Bootstrap admin pertama**: tidak ada endpoint signup publik (staff account dibuat
oleh ADMIN lain lewat API BE-04 nanti). Untuk membuat ADMIN pertama di lingkungan
dev/staging, pakai CLI (butuh `DATABASE_URL` yang hidup — TIDAK dijalankan oleh test
suite):

```bash
uv run python -m app.cli create_admin --email admin@example.com
# akan prompt password interaktif (getpass, tidak masuk shell history);
# atau non-interaktif: --password 'S0meStrongPass!'
```

Idempotent: menjalankan ulang untuk email yang sama tidak membuat duplikat atau
menimpa akun yang sudah ada.

**Test** (`tests/test_security.py`, `tests/test_auth_service.py`,
`tests/test_auth_router.py`) murni unit/in-memory — tidak butuh Postgres live:
hashing, encode/decode JWT (termasuk expired & wrong-secret), `authenticate`/
`refresh_access_token` dengan fake repository, dan endpoint HTTP lewat
`TestClient` dengan `app.dependency_overrides[get_staff_account_repository]`
di-override ke repo in-memory palsu.

> **Yang WAJIB diverifikasi manual oleh siapa pun yang punya Postgres live**
> sebelum menganggap BE-03 selesai secara penuh:
> - `uv run alembic upgrade head` (migration `48b08e41d49a`) sukses menambah
>   `password_hash` dan melonggarkan `oidc_sub` jadi nullable pada `staff_accounts`
>   sungguhan (sudah diverifikasi via `--sql` dry-run di sini, belum terhadap DB nyata),
> - `uv run python -m app.cli create_admin --email ... --password ...` benar-benar
>   membuat baris di `staff_accounts` dengan `role=ADMIN` dan `password_hash` terisi,
> - `POST /auth/login` dengan kredensial admin tsb di server yang jalan (`uv run
>   uvicorn app.main:app`) benar-benar mengembalikan token yang valid untuk
>   `GET /auth/me`, dan `POST /auth/refresh` dengan refresh token-nya berhasil.

## Celery worker infra (BE-07)

NFR-OPS-02 (FSD-AI.md): "Training and enrollment-processing are async and
retryable (idempotent jobs, dead-letter handling)." `app/worker/` implements
the generic worker infra (retry/idempotency/dead-letter) — it does **not**
implement the real QC/embedding logic, which is TR-02/TR-03 (`ai-training/`,
ai-engineer) scope.

```
app/worker/
  celery_app.py   # Celery instance — broker/backend = Settings.redis_url (XC-02, reused, no separate config)
  tasks.py        # DeadLetterTask base class + run_enrollment_qc (BE-07 stub, TR-02 replaces its body)
```

### Job semantics

- **Retry**: every task is declared with `autoretry_for=(...)`,
  `retry_backoff=True`, `retry_jitter=True`, `max_retries=5` (see
  `run_enrollment_qc`). This is stock Celery — exponential backoff with
  jitter, capped by `retry_backoff_max`.
- **Idempotency**: state-machine-driven, not a separate idempotency-key
  table. `run_enrollment_qc(session_id)` only does work if
  `enrollment_session.state == QC_RUNNING`; a duplicate delivery after the
  session has already moved on (`QC_PASSED`, `REJECTED_QUALITY`,
  `CANCELLED`, ...) is a no-op (logged as `audit_logs` action
  `job.qc_stub_skipped`). This mirrors
  `app/services/enrollment_state_machine.py`'s existing pattern instead of
  introducing a second mechanism.
- **Dead-letter handling**: no separate DLQ table/queue — `DeadLetterTask`
  (the `base=` for every task) writes one `audit_logs` row with
  `action="job.dead_letter"` from its `on_failure` hook, which Celery calls
  once a task fails *permanently* (for an `autoretry_for` task: after
  `max_retries` is exhausted). Observe the DLQ with:

  ```sql
  SELECT * FROM audit_logs
  WHERE action = 'job.dead_letter'
  ORDER BY at DESC;
  ```

  `payload` carries `{task, task_id, args, kwargs, exception_type,
  exception_message}`.

### `run_enrollment_qc` — BE-07 stub, NOT the real QC pipeline

`app/worker/tasks.py::run_enrollment_qc` (and its inner
`_run_enrollment_qc_stub`) checks idempotency, writes an `audit_logs` entry
(`action="job.qc_stub_executed"`, payload notes "real QC pipeline: TR-02"),
and returns — it never transitions the session to `QC_PASSED` /
`REJECTED_QUALITY` (that's an AI-model decision, TR-02's job, not BE-07's).
TR-02 replaces this task's **body only**; its name/signature/decorator stay
the same so `app/services/qc_queue.py` (BE-06's integration seam,
`enqueue_qc_job(session_id)`) never has to change again.

`enqueue_qc_job` dispatches with `run_enrollment_qc.delay(str(session_id))`
and swallows/logs any broker-connection error — dispatch is best-effort so
`POST /enrollments/{id}/complete` (BE-06) always still returns 200 even if
Redis is down; the session then simply stays `QC_RUNNING` until the job is
(re)dispatched.

### Running the worker

```bash
# local (needs REDIS_URL / DATABASE_URL, e.g. via docker compose up postgres redis)
uv run celery -A app.worker.celery_app worker --loglevel=info

# or, via docker compose (root repo) — starts `backend` + `celery-worker` +
# infra (postgres/redis/minio/mlflow) together:
docker compose -f docker-compose.dev.yml --profile app up
```

### Test (`tests/test_worker_tasks.py`)

Pure unit tests — no live Redis/Postgres:
`celery_app.conf.task_always_eager = True` runs tasks synchronously
in-process (Celery's real retry/`on_failure` machinery still executes, just
without a broker round-trip); the DB layer is faked (`FakeEnrollmentRepo`/
`FakeAuditRepo`/`_FakeDbSession`, same style as `tests/test_media_service.py`).
Covers: idempotency skip (session already past `QC_RUNNING`), successful
stub execution + audit entry, retry config assertions
(`autoretry_for`/`retry_backoff`/`max_retries`), and a simulated
always-fails task proving a `job.dead_letter` audit entry is written once
retries are exhausted.

> **Yang WAJIB diverifikasi manual oleh siapa pun yang punya Redis+Postgres
> live** (lihat instruksi di laporan task BE-07) sebelum menganggap dead-letter
> handling teruji end-to-end sungguhan (bukan cuma eager-mode unit test):
> - jalankan `docker compose -f docker-compose.dev.yml up postgres redis` lalu
>   `uv run celery -A app.worker.celery_app worker --loglevel=info` di satu
>   terminal,
> - di terminal lain, `uv run python -c "from app.worker.tasks import
>   run_enrollment_qc; run_enrollment_qc.delay('<uuid-sesi-QC_RUNNING>')"`
>   untuk memicu job sungguhan lewat Redis broker,
> - untuk memicu dead-letter sungguhan: enqueue job dengan `session_id` yang
>   membuat lookup DB gagal berulang (mis. matikan Postgres sesaat setelah
>   dispatch) atau tempel sementara `raise ConnectionError(...)` di awal
>   `_run_enrollment_qc_stub` lalu jalankan — tunggu backoff 5x retry, lalu
>   cek `SELECT * FROM audit_logs WHERE action = 'job.dead_letter'`.

## Retention automation (BE-14, ASM-10, NFR-SEC-03)

`app/services/retention_service.py` implements two idempotent jobs, wrapped
as Celery tasks in `app/worker/tasks.py`
(`backfill_retention_expiry_task` / `purge_expired_media_task`):

- **`backfill_retention_expiry`** ("lifecycle verification") — sets
  `media_objects.retention_expires_at` on FINALIZED rows that don't have it
  yet. PHOTO/VIDEO (raw enrollment media) anchor on the owning
  `enrollment_sessions.updated_at` at the moment it reached `ENROLLED`
  (ASM-10 default: +90 days, `RETENTION_RAW_MEDIA_DAYS`); EVENT_FRAME
  (door-camera frames, independent of any enrollment session) anchors on the
  media row's own `created_at` (+30 days default, `RETENTION_EVENT_FRAME_DAYS`
  — a placeholder pending IN-06 calibration). See the module docstring for
  why the `ENROLLED`-session anchor is an intentionally conservative
  approximation (media can end up retained slightly *longer* than the
  configured window, never shorter).
- **`purge_expired_media`** — hard-deletes every `media_objects` row whose
  `retention_expires_at` has passed: S3 object, then DB row, then one
  `audit_logs` entry (`action="media.retention_purged"`) per deleted item.
  Per-item try/except so one failure (S3 timeout, etc.) doesn't stop the
  batch; a 404/already-absent S3 object is treated as success, not failure.

**This is the first Celery Beat schedule in this project** — every task
before BE-14 was on-demand only. The schedule itself
(`app/worker/celery_app.py::celery_app.conf.beat_schedule`) is inert unless
a *separate* beat process is actually running:

```bash
# Terminal 1 — executes whatever beat enqueues (same as any other job):
uv run celery -A app.worker.celery_app worker --loglevel=info

# Terminal 2 — enqueues backfill-retention-expiry (hourly) and
# purge-expired-media (every 6h) on schedule. Without this process, the
# beat_schedule entries are registered but nothing ever fires them.
uv run celery -A app.worker.celery_app beat --loglevel=info
```

Both intervals are configurable via `RETENTION_BACKFILL_INTERVAL_SECONDS` /
`RETENTION_PURGE_INTERVAL_SECONDS`.

**Known gaps, deliberately out of scope for BE-14** (see
`app/services/retention_service.py` module docstring for the full
rationale):
- The `ENROLLED`-anchor timestamp is approximate because `ai-training/`
  (TR-02/TR-03) transitions `enrollment_sessions.state -> ENROLLED` via raw
  SQL, not through `app/services/enrollment_state_machine.py` — so
  `updated_at` may not always reflect exactly when embedding extraction
  finished. Direction of error is safe (retain longer, never delete sooner).
- `media_objects.session_id` is nullable since EC-TR-05 (migration
  `b2e6f9a1c4d7`), which is what actually representing an EVENT_FRAME row
  requires — but no code path writes one yet; that's the event-ingestion
  side (IN-06-style), still separate from BE-14. The purge/backfill logic
  here is already written generically against `kind == EVENT_FRAME` and
  needs no changes once that ingestion lands.

Tests: `tests/test_retention_service.py` (pure service-logic unit tests,
fake repos/S3 client, no live Postgres/S3) and the retention section of
`tests/test_worker_tasks.py` (beat schedule registration, task wiring,
one end-to-end eager-mode run).

## Re-enrollment-due policy (EC-BE-05, TSD-edge-cases.md A-5)

`app/services/reenroll_due_service.py::evaluate_reenroll_due` is a second
Celery Beat job (`reenroll_due_task` in `app/worker/tasks.py`, daily by
default — `REENROLL_DUE_CHECK_INTERVAL_SECONDS`) that flags
`users.reenroll_due=true` for any `ACTIVE` user matching EITHER of two
criteria:

- **Age**: the user's most recent `ENROLLED` enrollment session is older
  than `REENROLL_DUE_MAX_AGE_MONTHS` (default 24).
- **Score drift**: the moving average of GENUINE-accept
  `access_events.similarity` (decision=GRANTED) over the trailing
  `REENROLL_DUE_SCORE_WINDOW_DAYS` (default 90) is below `τ + margin`
  (`REENROLL_DUE_SCORE_MARGIN`, default 0.05), computed from at least
  `REENROLL_DUE_MIN_EVENTS_FOR_SCORE` (default 5) events — too few events is
  treated as "not enough signal", not "criterion met". τ is resolved from
  the `recognition_configs` GLOBAL/`normal`-mode override if one exists,
  else `REENROLL_DUE_SIMILARITY_THRESHOLD_FALLBACK` (default 0.35, a
  same-ballpark placeholder mirroring ai-inference's own default — backend
  has no MLflow client and does not share ai-inference's env, so it cannot
  read the "real" per-mode artefact default described in the TSD's OQ-6).

Flagging is **audited** (`audit_logs`, `action="user.reenroll_due_marked"`,
actor `system:reenroll-due-job`) and **idempotent**: a user already
`reenroll_due=true` (whether flagged by this job or by another producer —
e.g. a future ai-training backfill job flagging
`reenroll_due_reason="video_retention_expired"` when a legacy user's
enrollment video has left the 90-day retention window) is skipped entirely,
with no re-check and no duplicate audit entry. This job touches only
`users.reenroll_due*` + `audit_logs` — it never touches `media_objects`,
`face_embeddings`, or dispatches any capture/QC/training job.

Uses the SAME beat process as the retention jobs above (no separate `celery
beat` invocation needed) — see that section for how to actually run beat.

Tests: `tests/test_reenroll_due_service.py` (pure service-logic unit tests
covering both criteria independently/combined, the min-event-count guard,
τ resolution from `recognition_configs` vs the env fallback, and
idempotency across two runs) and the reenroll-due section of
`tests/test_worker_tasks.py` (beat schedule registration, task wiring).

## Konfigurasi

Semua config via environment variables (lihat `.env.example`; salin ke `.env` untuk dev lokal). Tidak ada secret di repo (NFR-OPS-03).

AWS S3 (bucket `frac-media`, **diprovision manual oleh manusia** — lihat `infra/terraform/README.md`, bukan oleh service ini): `AWS_REGION`, `AWS_S3_BUCKET_NAME`, `AWS_S3_PREFIX`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`. Field terakhir adalah `pydantic.SecretStr` (`app/core/config.py`) sehingga tidak pernah ikut ter-log/ter-print.

## Error handling

Semua error mengikuti RFC 9457 `application/problem+json`: `{type, title, status, detail?, instance?}` (+ `errors` untuk validation 422). Lihat `app/core/problem.py`.

## Observability (XC-04)

- **Structured logging**: JSON ke stdout, lihat `app/core/logging.py` (`setup_logging`, dipanggil di `create_app()`).
- **Metrics**: `GET /metrics` (Prometheus exposition format) — histogram `backend_http_request_duration_seconds` + counter `backend_http_requests_total`, dicatat oleh middleware di `app/main.py` untuk setiap request (label `method`/`route`/`status`). Lihat `app/core/metrics.py`.
- **Tracing (opsional/lazy)**: OTel, dimatikan secara default. Aktifkan dengan `uv sync --extra otel` lalu set `OTEL_EXPORTER_OTLP_ENDPOINT` (mis. `http://localhost:4317`); tanpa keduanya, `setup_tracing()` di `app/core/tracing.py` adalah no-op — service tetap jalan normal di dev/CI tanpa collector.
