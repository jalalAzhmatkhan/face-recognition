# QA Harness — Face Recognition Access Control

Harness QA (pytest + Playwright + httpx) untuk seluruh service monorepo. Dimanage dengan `uv`.

## Setup

```bash
cd qa
uv sync                              # install dependencies (venv otomatis)
uv run playwright install chromium   # WAJIB sekali sebelum menjalankan test E2E
```

## Menjalankan test

```bash
uv run pytest                 # default: hanya test yang TIDAK butuh service hidup
uv run pytest -m live         # smoke test terhadap service yang sedang berjalan
uv run pytest -m ""           # semua test (live + non-live)
uv run ruff check             # lint
```

Test yang membutuhkan service hidup ditandai `@pytest.mark.live` dan di-skip by default
(dikonfigurasi via `addopts = "-ra -m 'not live'"` di `pyproject.toml`), sehingga
`uv run pytest` selalu hijau di CI tanpa perlu menghidupkan service.

## Konfigurasi (env vars)

| Variabel | Default | Deskripsi |
|---|---|---|
| `QA_BACKEND_BASE_URL` | `http://localhost:8000` | Base URL backend FastAPI |
| `QA_FRONTEND_BASE_URL` | `http://localhost:5173` | Base URL frontend |
| `QA_INFERENCE_BASE_URL` | `http://localhost:8001` | Base URL ai-inference |
| `QA_HTTP_TIMEOUT_S` | `10.0` | Timeout HTTP client (detik) |

## Struktur

```
qa/
├── conftest.py          # fixtures global: QASettings, base-URL, httpx clients
├── fixtures/            # data fixture (video 360° dummy, payload contoh, dst.)
├── tests/
│   ├── api/             # API contract & smoke tests (httpx)
│   ├── e2e/             # E2E browser tests (Playwright)
│   └── security/        # security/privacy tests (deny-by-default, RBAC, dst.)
└── pyproject.toml
```

## Markers

- `live` — butuh service hidup; skip by default.
- `api`, `e2e`, `security` — kategorisasi suite; filter dengan `-m`, mis. `uv run pytest -m "api and not live"`.

## Gate QA

Sesuai workflow repo: fitur hanya boleh dibuka PR setelah QA PASSED. Di CI, job QA
menjalankan `uv run pytest` (dan suite `live` terhadap environment compose bila tersedia);
job fail = PR terblokir.
