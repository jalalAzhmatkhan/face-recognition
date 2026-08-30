# Face Recognition Access Control — Monorepo

Aplikasi face recognition untuk otorisasi akses masuk gedung/kantor. Orang yang diberi otorisasi di-enroll dengan capture foto/video wajah 360° (mulai arah jam 12, berputar searah jarum jam kembali ke jam 12), lalu model di-training/fine-tune, dan dipakai untuk inferensi real-time di pintu masuk.

## Struktur Monorepo (modular)

- `frontend/` — UI web (enrollment capture, manajemen user, monitoring akses)
- `backend/` — Service backend: Python FastAPI + Pydantic + alembic, dimanage dengan `uv`
- `ai-inference/` — Service inferensi face recognition (Python/PyTorch; boleh Rust bila perlu latensi rendah)
- `ai-training/` — Pipeline data engineering, EDA, feature extraction, training/fine-tuning, experiment tracking (Python + PyTorch GPU + Pydantic, dimanage `uv`)
- `qa/` — Quality Assurance: Python + Playwright, dimanage `uv`
- `documentation/` — Semua dokumen perencanaan & desain. **Hanya FSD dan TSD yang di-commit** (lihat .gitignore)

## Aturan Non-Negotiable

1. **Media tidak boleh disimpan lokal.** Semua foto/video hasil capture WAJIB disimpan di AWS S3 (upload langsung / presigned URL). Lokal hanya boleh buffer sementara in-memory/temp yang langsung dihapus.
2. **Metrik evaluasi model** (urutan prioritas): **Recall (utama)** → F1 score → Precision. Plus **inference speed dalam milidetik** sebagai metrik operasional.
3. **Enrollment 360°**: capture bukan hanya frontal — rekam video wajah menghadap arah jam 12 lalu berputar searah jarum jam sampai kembali ke jam 12, untuk mendapatkan view fitur wajah 360°.

## Tech Stack

| Area | Stack |
|---|---|
| Backend | Python, FastAPI, Pydantic, alembic, `uv` |
| AI Training | Python, PyTorch (GPU), Pydantic, alembic (bila perlu), `uv` |
| AI Inference | Python/PyTorch; Rust diperbolehkan untuk latensi rendah |
| QA | Python + Playwright, `uv` |
| Storage media | AWS S3 |
| Frontend | Ditentukan oleh System Analyst + Frontend Engineer (lihat FSD/TSD) |

## Workflow Pengembangan (Git Flow)

1. Buat branch dari `master`: `features/<nama_fitur>` (fitur) atau `bugfix/<nama_bug>` (bug).
2. Implementasi di branch tersebut. Commit dan push ke remote.
3. QA harus PASSED sebelum buka Pull Request.
4. Buka Pull Request ke branch `master`.
5. Pastikan CI passed, lalu merge PR ke `master`, hapus branch yang tidak terpakai.
6. Di `master` ter-update, jalankan `graphify update .`
7. Terakhir: bump version + git tag.

### Aturan Versioning (SemVer)

- Implementasi fitur → bump **minor**
- Patch/bugfix → bump **patch**
- Bump **major** HANYA dengan perintah eksplisit dari user

## Tooling Wajib

- **`graphify`** — gunakan untuk membaca kondisi repo saat ini, JANGAN membaca whole repository/whole code langsung. Jalankan `graphify update .` di `master` setelah merge PR, sebelum bump version. Folder `.claude/` di-ignore oleh graphify.
- **`rtk`** (Rust Token Killer) — gunakan untuk menghemat token pada operasi dev (git, dll).

## Agents

Definisi agent ada di `.claude/agents/` (tidak di-commit):

| Agent | Peran |
|---|---|
| `system-analyst` | Grooming, analisis requirement & impact, desain sistem high-level, menulis FSD (versi AI + versi layman) dan TSD, rekomendasi tools |
| `ai-researcher` | Riset SOTA face recognition dari paper 5 tahun terakhir, rekomendasi implementasi teknis AI |
| `uiux-designer` | Design tokens, perencanaan screen, user flow, UX yang smooth & engaging |
| `project-manager` | Manajemen proyek, breakdown & scheduling task, audit report & checkpoint |
| `ai-engineer` | End-to-end AI service: data engineering, preprocessing, EDA, warehousing, feature extraction, eksperimen, training, tracking, inference service |
| `backend-engineer` | Service backend FastAPI + migrasi database (alembic) |
| `frontend-engineer` | Implementasi fitur UI frontend |
| `qa-engineer` | QA dengan Python + Playwright |

## Struktur `documentation/`

- `documentation/fsd/` — FSD (di-commit): `FSD-AI.md` (untuk AI), `FSD-USER.md` (untuk layman)
- `documentation/tsd/` — TSD (di-commit)
- `documentation/research/` — hasil riset AI Researcher (TIDAK di-commit)
- `documentation/planning/` — output Project Manager: task breakdown, schedule, checkpoint, audit (TIDAK di-commit)
- `documentation/uiux/` — output UI/UX Designer: design tokens, screen plan, user flows (TIDAK di-commit)
- `documentation/qa/` — test plan & laporan QA (TIDAK di-commit)
