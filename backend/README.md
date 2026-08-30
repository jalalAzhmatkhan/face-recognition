# backend — Core API

FastAPI + Pydantic v2, dimanage dengan [`uv`](https://docs.astral.sh/uv/). Python ≥ 3.12.

## Layering

```
app/
  routers/        # HTTP layer (FastAPI routers) — deny-by-default auth deps mulai BE-03
  services/       # Business logic / orchestration
  repositories/   # Data access (SQLAlchemy + alembic mulai BE-02)
  core/           # config (pydantic-settings), structured logging, RFC 9457 errors
tests/            # pytest
```

## Menjalankan

```bash
uv sync                                   # install deps (buat .venv)
uv run uvicorn app.main:app --reload      # http://localhost:8000/healthz
uv run pytest                             # test
uv run ruff check .                       # lint
```

## Konfigurasi

Semua config via environment variables (lihat `.env.example`; salin ke `.env` untuk dev lokal). Tidak ada secret di repo (NFR-OPS-03).

AWS S3 (bucket `frac-media`, **diprovision manual oleh manusia** — lihat `infra/terraform/README.md`, bukan oleh service ini): `AWS_REGION`, `AWS_S3_BUCKET_NAME`, `AWS_S3_PREFIX`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`. Field terakhir adalah `pydantic.SecretStr` (`app/core/config.py`) sehingga tidak pernah ikut ter-log/ter-print.

## Error handling

Semua error mengikuti RFC 9457 `application/problem+json`: `{type, title, status, detail?, instance?}` (+ `errors` untuk validation 422). Lihat `app/core/problem.py`.

## Observability (XC-04)

- **Structured logging**: JSON ke stdout, lihat `app/core/logging.py` (`setup_logging`, dipanggil di `create_app()`).
- **Metrics**: `GET /metrics` (Prometheus exposition format) — histogram `backend_http_request_duration_seconds` + counter `backend_http_requests_total`, dicatat oleh middleware di `app/main.py` untuk setiap request (label `method`/`route`/`status`). Lihat `app/core/metrics.py`.
- **Tracing (opsional/lazy)**: OTel, dimatikan secara default. Aktifkan dengan `uv sync --extra otel` lalu set `OTEL_EXPORTER_OTLP_ENDPOINT` (mis. `http://localhost:4317`); tanpa keduanya, `setup_tracing()` di `app/core/tracing.py` adalah no-op — service tetap jalan normal di dev/CI tanpa collector.
