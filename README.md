# Face Recognition Access Control

Monorepo untuk sistem face recognition otorisasi akses masuk gedung/kantor. Enrollment memakai capture foto + video wajah 360° (rotasi searah jarum jam dari arah jam 12), model di-fine-tune, lalu dipakai inferensi real-time di pintu masuk.

Dokumen sumber: `documentation/fsd/FSD-AI.md` (requirement) dan `documentation/tsd/TSD.md` (arsitektur & tech stack).

## Struktur

| Direktori | Isi | Stack |
|---|---|---|
| `frontend/` | Web console: enrollment capture, manajemen user/device, monitoring | React + TS + Vite (proposed) |
| `backend/` | Core API: auth, users, enrollment orchestration, presigned S3, events, audit | Python 3.12+, FastAPI, Pydantic v2, alembic, `uv` |
| `ai-inference/` | Service inferensi hot path pintu (detect → align → liveness → embed → ANN) | Python + PyTorch (opsional Rust fase 2) |
| `ai-training/` | Data engineering, EDA, fine-tuning, evaluasi, registry publishing | Python + PyTorch GPU, `uv` |
| `qa/` | E2E, API contract, model-regression gate | Python + Playwright, `uv` |
| `documentation/` | FSD & TSD (hanya keduanya yang di-commit) | — |

## Development

Prasyarat: [`uv`](https://docs.astral.sh/uv/), Docker (opsional untuk infra), Node.js (untuk `frontend/`).

```bash
# Backend
cd backend
uv sync
uv run uvicorn app.main:app --reload   # http://localhost:8000/healthz

# Infra dev (kerangka; PG/Redis/MLflow lengkap menyusul di task XC-02)
docker compose -f docker-compose.dev.yml up
```

Konfigurasi via environment variables (lihat `backend/.env.example`). **Tidak ada secret di repo** dan **media (foto/video) tidak pernah disimpan lokal** — semua media ke AWS S3 via presigned URL.

## Workflow

Branch dari `master`: `features/<nama_fitur>` atau `bugfix/<nama_bug>`. QA harus PASSED sebelum PR. CI (`.github/workflows/ci.yml`) menjalankan lint + test per service secara path-filtered.
