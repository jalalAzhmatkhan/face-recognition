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

## Konfigurasi

Semua config via environment variables (lihat `.env.example`; salin ke `.env` untuk dev lokal). Tidak ada secret di repo (NFR-OPS-03).

AWS S3 (bucket `frac-media`, **diprovision manual oleh manusia** — lihat `infra/terraform/README.md`, bukan oleh service ini): `AWS_REGION`, `AWS_S3_BUCKET_NAME`, `AWS_S3_PREFIX`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`. Field terakhir adalah `pydantic.SecretStr` (`app/core/config.py`) sehingga tidak pernah ikut ter-log/ter-print.

## Error handling

Semua error mengikuti RFC 9457 `application/problem+json`: `{type, title, status, detail?, instance?}` (+ `errors` untuk validation 422). Lihat `app/core/problem.py`.

## Observability (XC-04)

- **Structured logging**: JSON ke stdout, lihat `app/core/logging.py` (`setup_logging`, dipanggil di `create_app()`).
- **Metrics**: `GET /metrics` (Prometheus exposition format) — histogram `backend_http_request_duration_seconds` + counter `backend_http_requests_total`, dicatat oleh middleware di `app/main.py` untuk setiap request (label `method`/`route`/`status`). Lihat `app/core/metrics.py`.
- **Tracing (opsional/lazy)**: OTel, dimatikan secara default. Aktifkan dengan `uv sync --extra otel` lalu set `OTEL_EXPORTER_OTLP_ENDPOINT` (mis. `http://localhost:4317`); tanpa keduanya, `setup_tracing()` di `app/core/tracing.py` adalah no-op — service tetap jalan normal di dev/CI tanpa collector.
