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

## Error handling

Semua error mengikuti RFC 9457 `application/problem+json`: `{type, title, status, detail?, instance?}` (+ `errors` untuk validation 422). Lihat `app/core/problem.py`.
