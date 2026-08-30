# backend — Core API

FastAPI + Pydantic v2, dimanage dengan [`uv`](https://docs.astral.sh/uv/). Python ≥ 3.12.

## Layering

```
app/
  routers/        # HTTP layer (FastAPI routers) — deny-by-default auth deps mulai BE-03
  services/       # Business logic / orchestration
  repositories/   # Data access — query helpers atas app/models (BE-02: contoh `users.py`)
  models/         # SQLAlchemy 2.x ORM models, satu module per tabel TSD §4 (BE-02)
  db/             # engine/session (BE-02)
  core/           # config (pydantic-settings), structured logging, RFC 9457 errors
migrations/       # alembic (BE-02)
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
itu harus lewat mekanisme secret yang sama dengan kredensial lain (NFR-OPS-03).

## Konfigurasi

Semua config via environment variables (lihat `.env.example`; salin ke `.env` untuk dev lokal). Tidak ada secret di repo (NFR-OPS-03).

AWS S3 (bucket `frac-media`, **diprovision manual oleh manusia** — lihat `infra/terraform/README.md`, bukan oleh service ini): `AWS_REGION`, `AWS_S3_BUCKET_NAME`, `AWS_S3_PREFIX`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`. Field terakhir adalah `pydantic.SecretStr` (`app/core/config.py`) sehingga tidak pernah ikut ter-log/ter-print.

## Error handling

Semua error mengikuti RFC 9457 `application/problem+json`: `{type, title, status, detail?, instance?}` (+ `errors` untuk validation 422). Lihat `app/core/problem.py`.

## Observability (XC-04)

- **Structured logging**: JSON ke stdout, lihat `app/core/logging.py` (`setup_logging`, dipanggil di `create_app()`).
- **Metrics**: `GET /metrics` (Prometheus exposition format) — histogram `backend_http_request_duration_seconds` + counter `backend_http_requests_total`, dicatat oleh middleware di `app/main.py` untuk setiap request (label `method`/`route`/`status`). Lihat `app/core/metrics.py`.
- **Tracing (opsional/lazy)**: OTel, dimatikan secara default. Aktifkan dengan `uv sync --extra otel` lalu set `OTEL_EXPORTER_OTLP_ENDPOINT` (mis. `http://localhost:4317`); tanpa keduanya, `setup_tracing()` di `app/core/tracing.py` adalah no-op — service tetap jalan normal di dev/CI tanpa collector.
