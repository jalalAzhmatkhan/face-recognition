# Face Recognition Access Control

Sistem otorisasi akses fisik ke gedung/kantor menggunakan pengenalan wajah (face recognition), dibangun sebagai **modular monorepo**.

> Dokumen sumber kebenaran: [`documentation/fsd/FSD-AI.md`](documentation/fsd/FSD-AI.md) (requirement, machine-readable), [`documentation/fsd/FSD-USER.md`](documentation/fsd/FSD-USER.md) (requirement, bahasa awam), [`documentation/tsd/TSD.md`](documentation/tsd/TSD.md) (arsitektur & spesifikasi teknis). README ini merangkum ketiganya untuk onboarding cepat — kalau ada perbedaan, dokumen FSD/TSD yang menang.

---

## Daftar Isi

1. [Tujuan Proyek](#1-tujuan-proyek)
2. [Service yang Dibangun](#2-service-yang-dibangun)
3. [Struktur Folder](#3-struktur-folder)
4. [Tech Stack](#4-tech-stack)
5. [Prasyarat & Cara Menjalankan](#5-prasyarat--cara-menjalankan)
6. [Flow Bisnis & User Sequence](#6-flow-bisnis--user-sequence)
7. [High-Level Architecture](#7-high-level-architecture)
8. [Flow Logic AI: Deteksi → Liveness → Ekstraksi Fitur → Keputusan](#8-flow-logic-ai-deteksi--liveness--ekstraksi-fitur--keputusan)
9. [Paper Referensi](#9-paper-referensi)

---

## 1. Tujuan Proyek

Menggantikan otorisasi akses manual (kartu/PIN) di gedung/kantor dengan **verifikasi wajah otomatis** yang:

- **Aman** — data biometrik (foto/video/embedding) diperlakukan sebagai data pribadi sensitif (UU PDP No. 27/2022): consent eksplisit sebelum capture, enkripsi at-rest (S3 SSE-KMS), retensi terbatas (90 hari untuk media mentah), dan hak hapus (revoke → embedding & media dihapus, user tidak lagi dikenali dalam ≤24 jam).
- **Akurat dengan prioritas yang jelas** — metrik evaluasi model diurutkan **Recall (utama) → F1 → Precision**, karena bagi sistem access control, gagal mengenali karyawan sah (false reject) jauh lebih mengganggu operasional daripada precision yang sedikit lebih longgar — namun tetap dikendalikan dengan batas *false accept rate* (FAR) yang ketat lewat threshold tuning, bukan Recall tanpa batas.
- **Cepat** — keputusan akses di pintu diukur dalam **milidetik** (`latency_ms`), dengan target p95 ≤ 300 ms end-to-end.
- **Auditable** — setiap enrollment, perubahan status, keputusan akses, dan promosi model tercatat di audit log *append-only*.

**Alur inti (core loop):**

```
Enroll (capture foto + video orientasi kepala) → Simpan media di AWS S3
  → Quality Check + ekstraksi fitur wajah → Bangun galeri embedding
  → Model dipakai untuk inferensi real-time di pintu
  → Keputusan Grant/Deny + audit log
```

**Non-negotiable rules** (tidak bisa dikompromikan di implementasi manapun):

1. **Media (foto/video) tidak pernah disimpan di disk lokal service manapun** — upload langsung browser→S3 via presigned URL; worker hanya streaming in-memory/temp-file yang segera dihapus.
2. **Urutan metrik evaluasi model**: Recall (utama) → F1 → Precision, ditambah *inference speed* dalam milidetik sebagai metrik operasional.
3. **Enrollment "360°"** berarti **orientasi kepala** (yaw + pitch: menoleh, menunduk, mendongak mengikuti 12 posisi jam) — **bukan** badan/kamera yang berputar. Wajah selalu menghadap kamera sepanjang capture, sehingga tidak ada segmen "belakang kepala" yang perlu dibuang.

---

## 2. Service yang Dibangun

| Service | Direktori | Tanggung Jawab | Status |
|---|---|---|---|
| **Web Console** | [`frontend/`](frontend/) | UI enrollment (capture 360°), manajemen user & enrollment, login staff, (rencana) monitoring live & dashboard | ✅ Auth, users, enrollment capture & management jalan |
| **Core API** | [`backend/`](backend/) | AuthN/Z staff (JWT+RBAC), CRUD users, orkestrasi enrollment (state machine + consent), presigned upload S3, revocation cascade, job async (Celery), audit log | ✅ Fondasi lengkap; devices/access-events/training-API menyusul |
| **Inference Service** | [`ai-inference/`](ai-inference/) | Hot path pintu: deteksi → alignment → liveness → embedding → pencarian galeri → keputusan grant/deny | 🔲 Scaffold saja; pipeline `/recognize` menyusul |
| **Training Pipeline** | [`ai-training/`](ai-training/) | Data engineering dari S3, quality-check media, ekstraksi fitur & embedding, dataset snapshot, EDA, (rencana) fine-tuning & evaluasi | ✅ QC pipeline, dataset snapshot, EDA jalan nyata (model embedding masih placeholder) |
| **QA** | [`qa/`](qa/) | E2E test (Playwright), API contract test, no-local-media enforcement, regression metrik model | ✅ Harness siap; suite lengkap menyusul |

Status detail per task ada di `documentation/planning/task-breakdown.md` (tidak di-commit — internal tim).

---

## 3. Struktur Folder

```
face-recognition/
├── frontend/                # React + TS + Vite — web console
│   └── src/
│       ├── app/              # Shell, routing, auth guard
│       ├── features/         # Modul per domain (enrollment-capture, enrollment-management, user-management)
│       ├── lib/               # Util bersama (auth token/JWT)
│       ├── pages/             # Halaman per route
│       └── styles/            # Design tokens (CSS variables)
│
├── backend/                  # Python FastAPI — Core API
│   └── app/
│       ├── routers/           # HTTP endpoints
│       ├── services/          # Business logic (state machine, revocation, dst.)
│       ├── repositories/      # Akses data
│       ├── models/            # SQLAlchemy ORM
│       ├── worker/             # Celery app + task (stub QC, di-override ai-training)
│       └── core/               # Config, logging, error handling, security
│
├── ai-inference/              # Python FastAPI — inference hot-path (scaffold)
│
├── ai-training/                # Python — training pipeline
│   └── src/ai_training/
│       ├── quality/             # Deteksi wajah + pose + quality-check (QC)
│       ├── embedding/            # Alignment, sampling, embedder (interface)
│       ├── data/                  # Dataset snapshot builder
│       ├── eda/                    # EDA report generator
│       ├── db/                      # Akses Postgres (raw SQL, role terbatas)
│       ├── worker/                   # Celery worker (consumer task QC dari backend)
│       └── models/                    # Model asset (mis. face_landmarker.task)
│
├── qa/                          # Python + Playwright — automated QA
│
├── infra/terraform/              # Infrastructure-as-Code referensi (S3/KMS/IAM — TIDAK pernah di-apply otomatis)
│
├── documentation/
│   ├── fsd/                        # ✅ DI-COMMIT — Functional Spec (AI + user-facing)
│   ├── tsd/                         # ✅ DI-COMMIT — Technical Spec
│   ├── research/                     # ⬜ tidak di-commit — literature review & rekomendasi
│   ├── planning/                      # ⬜ tidak di-commit — task breakdown, jadwal
│   ├── uiux/                            # ⬜ tidak di-commit — design tokens, user flow, screen plan
│   └── qa/                               # ⬜ tidak di-commit — test plan
│
├── docker-compose.dev.yml         # Infra dev: Postgres+pgvector, Redis, MinIO, MLflow
├── VERSION                         # SemVer, sumber tag rilis
└── .github/workflows/ci.yml         # CI: lint+test per service, path-filtered
```

---

## 4. Tech Stack

| Layer | Stack | Catatan |
|---|---|---|
| **Frontend** | React 19, TypeScript, Vite 8, TanStack Query 5, React Router 7 | Face detection browser-side: `@vladmandic/face-api` (model self-hosted, tanpa CDN) |
| **Backend (Core API)** | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 + Alembic, `uv` | Auth: PyJWT (HS256) + Argon2id; error format RFC 9457 (problem+json) |
| **AI Training** | Python 3.12, OpenCV (headless), MediaPipe Tasks API, NumPy, `uv` | PyTorch/MLflow/boto3 di-lazy-import (extra `ml`) agar test dasar tetap ringan |
| **AI Inference** | Python + PyTorch (rencana; Rust/ONNX Runtime opsional fase 2 bila SLA latensi tidak tercapai) | |
| **Database** | PostgreSQL 16 + **pgvector** (HNSW, cosine) | Satu engine untuk data bisnis + vector; role DB terpisah per service (least-privilege) |
| **Cache & Broker** | Redis 7 | Cache policy hot-path (TTL ≤30s) + broker Celery |
| **Object Storage** | AWS S3 (SSE-KMS, private, presigned URL) | **Wajib** — media tidak boleh di disk lokal manapun. Dev/test pakai MinIO (S3-compatible) |
| **Async Jobs** | Celery | Retry dgn exponential backoff, dead-letter via `audit_logs`, idempotency berbasis state-machine |
| **Experiment Tracking** | MLflow (self-hosted, artifact di S3) | Model registry (`CANDIDATE` → `PRODUCTION` via promotion gate human-in-the-loop) |
| **QA** | Python + Playwright, `uv` | |
| **CI/CD** | GitHub Actions (path-filtered per service) | |
| **Observability** | Prometheus metrics + logging terstruktur (OTel tracing lazy-hook) | |

Semua service Python dimanage `uv`; frontend dengan `npm`.

---

## 5. Prasyarat & Cara Menjalankan

### 5.1 Prasyarat

- [`uv`](https://docs.astral.sh/uv/) (Python package/venv manager)
- Node.js ≥ 20 + `npm` (untuk `frontend/`)
- Docker + Docker Compose (untuk infra dev: Postgres, Redis, MinIO, MLflow, MailHog)
- (Opsional, hanya untuk `ai-training` extra `ml`) GPU + CUDA bila memakai PyTorch — CPU tetap bisa jalan untuk pipeline QC (OpenCV + MediaPipe)

### 5.2 Menjalankan via Docker Compose

**Opsi A — infra saja** (Postgres+pgvector, Redis, MinIO, MLflow, MailHog), lalu jalankan service aplikasi manual (§5.3) untuk iterasi tercepat:

```bash
docker compose -f docker-compose.dev.yml up -d postgres redis minio minio-init mlflow mailhog
```

Bucket `frac-media` otomatis dibuat oleh service `minio-init`. Kredensial default (**hanya untuk dev**, jangan dipakai di produksi) ada di `.env.example`.

**Opsi B — seluruh stack via Docker** (`backend`, `frontend`, `celery-worker`, `ai-inference`, `ai-training`, di bawah profile `app`), semuanya dengan hot-reload (bind-mount source ke container, jadi edit kode di host langsung tercermin tanpa rebuild):

```bash
docker compose -f docker-compose.dev.yml --profile app up -d \
  backend-migrate backend celery-worker frontend ai-inference ai-training
```

- `backend-migrate` adalah job one-shot (`alembic upgrade head`) yang jalan sekali sebelum `backend`/`celery-worker`/`ai-inference` start — tidak perlu dijalankan manual.
- Frontend: **http://localhost:5173** · Backend: **http://localhost:8000/healthz** · Inference: **http://localhost:8100/healthz**.
- `ai-inference`/`ai-training` meng-install extra `ml` (PyTorch — versi **CPU-only** dari index resmi PyTorch, bukan wheel default PyPI yang membawa ~40 paket `nvidia-*` CUDA berukuran total beberapa GB yang tidak berguna tanpa GPU — lihat `[tool.uv.sources]` di `pyproject.toml` masing-masing; jadi GPU **tidak** dipakai lewat compose ini) + `mediapipe`/`opencv`/`mlflow`/`onnxruntime` — image besar (beberapa ratus MB–1GB-an), build pertama kali cukup lama.
- Bobot image ditekan lewat **multi-stage build** di tiap `Dockerfile` (`builder` → `runtime`): stage `builder` menjalankan `uv sync`/`npm ci` (termasuk cache unduhan paket yang bisa sebesar venv/`node_modules` itu sendiri), lalu stage `runtime` hanya meng-copy hasil akhirnya (`.venv`/`node_modules` + source) — cache & binary `uv` tidak pernah ikut ke image final.
- Checkpoint AdaFace (~250MB, tidak di-commit — lisensi non-komersial diprocure terpisah) **tidak** ikut di-build ke image. Setelah `ai-training` up, unduh sekali:
  ```bash
  docker compose exec ai-training ai-training download-adaface-weights
  ```
  File hasil unduhan masuk ke `ai-training/models/` di host (bind-mount), jadi tetap ada walau container di-rebuild.
- `ai-inference`/`ai-training` tidak dikonfigurasi dengan GPU passthrough (`nvidia-container-toolkit`) — keduanya jalan CPU-only di dalam compose ini; training GPU sungguhan memakai infra pelatihan khusus (lihat fase TSD), bukan compose dev ini.

**Device tidak pernah jadi Online sendiri?** Status `ONLINE` sebuah device **hanya** diubah oleh device itu sendiri lewat `POST /devices/{id}/heartbeat` (kredensial device, bukan JWT staff) — sengaja tidak ada tombol/endpoint staff untuk "paksa online" (fail-secure). Karena firmware kamera pintu sungguhan tidak ada di monorepo ini, dev bisa mensimulasikannya dengan `scripts/device_simulator.py` (stdlib Python, tanpa dependency tambahan):

```bash
# kredensial (<credential_id>.<secret>) ditampilkan SEKALI saat POST /devices atau POST /devices/{id}/rotate-credential
python3 scripts/device_simulator.py --device-id <uuid> --credential <credential_id>.<secret>
```

Berjalan terus mengirim heartbeat tiap 30 detik (`--interval` bisa diubah, tapi jaga tetap di bawah 90 detik — ambang basi `Settings.device_heartbeat_stale_after_seconds`) sampai dihentikan (Ctrl+C), atau pakai `--once` untuk sekali kirim lalu keluar. Sejak FE ini juga tersedia dari browser: menu Devices → "⋮" → **Aktivasi (Simulasi Heartbeat)** (ADMIN only).

**Setup akun ADMIN pertama & lupa password.** Selain `python -m app.cli create_admin` (§5.3), first-run juga bisa lewat browser: buka **http://localhost:5173/setup** selama belum ada akun ADMIN sama sekali (halaman ini otomatis nonaktif/redirect ke `/login` begitu ≥1 akun ADMIN ada). Lupa password memakai SMTP asli yang disimulasikan lewat **MailHog** (dev-only fake SMTP, tidak benar-benar mengirim keluar) — klik "Lupa password?" di halaman login, lalu buka **http://localhost:8025** untuk melihat email tautan reset yang "terkirim".

### 5.3 Menjalankan Manual per Service

**Backend (Core API):**

```bash
cd backend
uv sync
cp .env.example .env   # isi DATABASE_URL, REDIS_URL, JWT_SECRET_KEY, AWS_* sesuai infra Anda
uv run alembic upgrade head
uv run python -m app.cli create_admin --email admin@example.com   # bootstrap akun ADMIN pertama
uv run uvicorn app.main:create_app --factory --reload   # http://localhost:8000/healthz
```

**Frontend (Web Console):**

```bash
cd frontend
npm install
echo "VITE_API_BASE_URL=http://localhost:8000" > .env.local
npm run dev   # http://localhost:5173
```

**AI Training (pipeline):**

```bash
cd ai-training
uv sync --extra ml   # instal opencv/mediapipe/torch/mlflow/boto3 (berat, opsional untuk sekadar baca kode)
export TRN_DB__DSN="postgresql://frac:frac_dev_password@localhost:5436/frac"
export TRN_S3__ENDPOINT_URL="http://localhost:9000"   # arahkan ke MinIO untuk dev
uv run ai-training snapshot --filter external_ref=<ref>   # build dataset snapshot
uv run ai-training eda --snapshot-id <id>                  # jalankan EDA report
uv run celery -A ai_training.worker.celery_app worker --loglevel=info   # worker QC/embedding
```

**QA:**

```bash
cd qa
uv sync
uv run playwright install chromium
uv run pytest              # unit/logic test (marker `live` di-skip default)
uv run pytest -m live       # butuh service lain jalan (backend/frontend/inference)
```

Konfigurasi selalu lewat environment variables (lihat `*/.env.example` masing-masing service) — **tidak ada secret di repo**.

---

## 6. Flow Bisnis & User Sequence

### 6.1 Enrollment — Mendaftarkan Karyawan Baru

Admin membuat sesi enrollment untuk karyawan, mendapatkan persetujuan (consent) tertulis/lisan yang tercatat, memandu karyawan merekam wajah, lalu sistem memvalidasi kualitas rekaman sebelum wajah tersebut "resmi terdaftar" dan bisa dikenali di pintu.

```mermaid
sequenceDiagram
    actor Admin
    actor Karyawan
    participant FE as Web Console
    participant API as Core API (backend)
    participant S3 as AWS S3
    participant Worker as Worker QC + Embedding (ai-training)
    participant DB as PostgreSQL

    Admin->>FE: Buat user baru + "Mulai Enrollment"
    FE->>API: POST /users, POST /enrollments {user_id}
    API->>DB: simpan user (ACTIVE) + sesi (state=CREATED)
    API-->>FE: sesi enrollment

    Admin->>Karyawan: Jelaskan & minta persetujuan
    Admin->>FE: Catat consent
    FE->>API: POST /enrollments/{id}/consent
    API->>DB: simpan consent + state=CONSENTED
    API-->>FE: siap capture

    Note over FE,Karyawan: Wizard capture 360° (orientasi kepala,<br/>bukan badan berputar)
    FE->>Karyawan: Panduan: 1 foto depan + video<br/>menoleh/menunduk/mendongak (12 posisi jam)
    FE->>API: POST /transition {target_state: CAPTURING}
    FE->>S3: Upload foto + video langsung (presigned URL)
    Note right of FE: Media TIDAK PERNAH<br/>lewat/disimpan di backend

    FE->>API: POST /enrollments/{id}/complete
    API->>S3: Validasi objek benar ada (HEAD check)
    API->>DB: state=CAPTURED lalu QC_RUNNING
    API--)Worker: enqueue job Quality Check (async)
    API-->>FE: 202 Accepted (proses berjalan di background)

    Worker->>S3: Ambil video (in-memory, tanpa disimpan lokal)
    Worker->>Worker: Deteksi wajah + cek 12 posisi jam<br/>+ cek blur/pencahayaan
    alt Kualitas tidak cukup
        Worker->>DB: state=REJECTED_QUALITY + alasan per posisi
        FE->>Admin: Tampilkan alasan, tombol "Rekam Ulang"
    else Kualitas lolos
        Worker->>Worker: Ekstraksi fitur wajah (embedding)<br/>per posisi jam
        Worker->>DB: Simpan embedding ke galeri (pgvector)
        Worker->>DB: state=ENROLLED
        FE->>Admin: "Karyawan berhasil terdaftar"
    end
```

**Poin penting untuk pembaca non-teknis:**
- **Consent dulu, baru rekam** — sistem tidak akan membuka akses ke kamera sebelum persetujuan tercatat.
- **Rekaman langsung ke cloud** — perangkat admin/karyawan tidak pernah menyimpan file foto/video; begitu selesai diunggah, tidak ada jejak file di komputer/browser.
- **Validasi otomatis** — kalau video kurang jelas (goyang, gelap, wajah tidak lengkap terlihat), sistem menolak dengan alasan spesifik dan meminta rekam ulang — bukan diterima seadanya.

### 6.2 Verifikasi Akses — Karyawan Masuk Gedung

```mermaid
sequenceDiagram
    actor Karyawan
    participant Dev as Kamera Pintu
    participant Inf as Inference Service
    participant Gallery as Galeri Wajah (pgvector)
    participant API as Core API
    participant Lock as Kunci Pintu

    Karyawan->>Dev: Berdiri di depan kamera
    Dev->>Inf: Kirim beberapa frame wajah
    Inf->>Inf: Deteksi wajah + cek "wajah asli" (liveness)
    alt Terindikasi foto/layar (spoofing)
        Inf-->>Dev: DITOLAK (dicurigai palsu)
        Inf--)API: catat event + tandai mencurigakan
        API-->>Admin: notifikasi ke petugas keamanan
    else Wajah asli terdeteksi
        Inf->>Inf: Ekstraksi fitur wajah
        Inf->>Gallery: Cari kecocokan tercepat
        Inf->>Inf: Bandingkan dengan ambang batas keputusan
        Inf-->>Dev: GRANTED / DENIED / TIDAK DIKENALI
        Inf--)API: catat event akses (async)
        opt Akses diberikan & status karyawan aktif
            API->>Lock: Perintah buka pintu
        end
    end
    Dev-->>Karyawan: Pintu terbuka / tetap terkunci
```

**Poin penting:**
- **Gagal aman (fail-secure)**: kalau ada gangguan sistem (mis. koneksi database terputus), pintu **tidak** otomatis terbuka — keamanan diutamakan di atas kenyamanan.
- **Karyawan yang di-nonaktifkan tidak pernah lolos**, walau wajahnya "cocok" secara teknis — status keaktifan selalu dicek bersamaan.
- Setiap upaya masuk (berhasil maupun ditolak) tercatat untuk keperluan audit.

### 6.3 Pelatihan & Promosi Model (Ringkas)

Model AI yang dipakai untuk mengenali wajah **tidak statis** — bisa dilatih ulang (fine-tune) memakai data yang terkumpul, dievaluasi, lalu baru dipakai di produksi setelah disetujui manusia (bukan otomatis). Lihat detail teknis di [§8](#8-flow-logic-ai-deteksi--liveness--ekstraksi-fitur--keputusan).

---

## 7. High-Level Architecture

```mermaid
flowchart LR
  subgraph Client["Sisi Pengguna"]
    FE["Web Console<br/>(frontend/)"]
    DEV["Kamera Pintu<br/>+ pengendali kunci"]
  end

  subgraph Core["Core Platform"]
    API["Core API<br/>(backend/, FastAPI)"]
    WK["Celery Workers"]
    PG[("PostgreSQL<br/>+ pgvector")]
    RD[("Redis<br/>cache + broker")]
  end

  subgraph AI["AI Platform"]
    INF["Inference Service<br/>(ai-inference/)"]
    TRN["Training Pipeline<br/>(ai-training/)"]
    MLF[("MLflow<br/>tracking + registry")]
  end

  S3[("AWS S3<br/>SSE-KMS, private")]

  FE -- "REST + JWT" --> API
  FE -- "Upload media (presigned URL)" --> S3
  DEV -- "Frame wajah / mTLS" --> INF
  INF -- "Keputusan + event" --> API
  API -- "Perintah buka pintu" --> DEV
  API <--> PG
  API <--> RD
  WK <--> RD
  WK -- "Baca media" --> S3
  WK -- "Tulis embedding" --> PG
  TRN -- "Baca dataset snapshot" --> S3
  TRN -- "Log eksperimen & model" --> MLF
  MLF -- "Artifact model" --> S3
  INF -- "Muat model" --> MLF
  INF -- "Cari kecocokan" --> PG
```

### Batasan Antar-Service (Aturan Wajib)

| Aturan | Alasan |
|---|---|
| `frontend/` tidak pernah bicara langsung ke DB/kredensial S3 — hanya panggil Core API dan upload byte ke presigned URL | Frontend adalah surface paling rentan (browser klien); kredensial sensitif tidak boleh bocor ke sana |
| `ai-inference/` adalah **satu-satunya** service di jalur keputusan pintu (hot path) — tidak boleh memanggil service lambat secara sinkron | Latensi keputusan harus dalam milidetik; event akses ditulis async (fire-and-forget + buffer lokal saat gangguan singkat) |
| `ai-training/` tidak pernah melayani trafik online — hanya mempublikasikan model versi baru ke registry; re-embedding galeri adalah job, bukan API | Memisahkan beban training (berat, GPU) dari jalur produksi (harus selalu responsif) |
| `backend/` memegang **semua** state bisnis (user, sesi, device, event, consent, audit) — service AI tidak punya tabel bisnis sendiri, hanya baca/tulis embedding & model | Satu sumber kebenaran untuk data operasional; role DB service AI dibatasi (least-privilege, tidak bisa baca `audit_logs`/data staff) |
| Byte media **tidak pernah** transit/menetap di disk service manapun | Non-negotiable rule proyek — browser→S3 langsung; worker streaming in-memory/`tmpfs` |

---

## 8. Flow Logic AI: Deteksi → Liveness → Ekstraksi Fitur → Keputusan

### 8.1 Pipeline Keputusan Akses (Real-Time di Pintu)

```mermaid
flowchart TD
    A["Frame wajah dari kamera pintu"] --> B["1. Deteksi Wajah + 5-Landmark<br/><i>SCRFD</i>"]
    B -->|"Tidak ada wajah"| Z1["UNKNOWN — tidak ada wajah terdeteksi"]
    B -->|"Wajah terdeteksi"| C["2. Alignment<br/>(similarity transform → 112×112)"]
    C --> D["3. Liveness / Anti-Spoofing<br/><i>MiniFASNet (fine-tuned)</i>"]
    D -->|"Terindikasi palsu (foto/layar/print)"| Z2["DENIED — spoof suspected<br/>+ alert petugas"]
    D -->|"Wajah asli (live)"| E["4. Ekstraksi Fitur (Embedding)<br/><i>AdaFace IR-50/IR-101, 512-d</i>"]
    E --> F["5. Pencarian Kemiripan di Galeri<br/>(cosine similarity, pgvector HNSW)<br/>vs multi-template per posisi jam"]
    F --> G{"Skor ≥ threshold τ<br/>DAN margin top1/top2 cukup?"}
    G -->|Tidak| Z3["UNKNOWN / DENIED —<br/>tidak cukup mirip siapa pun"]
    G -->|Ya| H{"Status user = ACTIVE?<br/>(cek cache Redis, TTL≤30s)"}
    H -->|"Tidak aktif / cache kosong"| Z4["DENIED — fail-secure"]
    H -->|Aktif| I["GRANTED — buka pintu"]

    style Z1 fill:#7c2d2d
    style Z2 fill:#7c2d2d
    style Z3 fill:#7c2d2d
    style Z4 fill:#7c2d2d
    style I fill:#1e5c33
```

Setiap tahap dicatat waktunya (`latency_ms`) secara terpisah dan diagregasi jadi anggaran total:

| Tahap | Anggaran (target, GPU kelas menengah) |
|---|---|
| Deteksi + landmark | ≤ 40 ms |
| Liveness | ≤ 60 ms |
| Ekstraksi fitur (embedding) | ≤ 50 ms |
| Pencarian galeri (ANN) | ≤ 10 ms |
| Overhead lain-lain | ≤ 40 ms |
| **Total keputusan (p95)** | **≤ 300 ms** |

### 8.2 Pipeline Enrollment: Video 360° → Galeri Embedding

```mermaid
flowchart TD
    A["Video orientasi kepala (webm)<br/>dari S3, in-memory"] --> B["Ekstraksi frame<br/>(sampling ~6 fps)"]
    B --> C["Per frame:<br/>Deteksi wajah + 468 landmark<br/><i>MediaPipe Face Landmarker</i>"]
    C --> D["Estimasi pose (yaw, pitch)<br/>via solvePnP terhadap model wajah 3D generik"]
    D --> E["Petakan ke salah satu dari<br/>12 posisi jam terdekat"]
    E --> F["Quality check per frame:<br/>blur (variance Laplacian),<br/>brightness, rasio ukuran wajah"]
    F --> G{"Cakupan posisi jam<br/>≥ ambang batas (mis. 75%)?"}
    G -->|Tidak| H["Sesi = REJECTED_QUALITY<br/>+ alasan per posisi jam"]
    G -->|Ya| I["Pilih K frame terbaik<br/>per posisi jam (coreset)"]
    I --> J["Alignment (112×112)<br/>+ ekstraksi embedding<br/><i>AdaFace</i>"]
    J --> K["Agregasi: 1 template embedding<br/>per posisi jam (multi-template)"]
    K --> L["Simpan ke galeri (pgvector)<br/>{user_id, model_version, pose_bucket}"]
    L --> M["Sesi = ENROLLED"]
```

### 8.3 Model yang Dipakai & Alasan Pemilihan

Rekomendasi ini disusun oleh riset literatur SOTA (±55 paper, 2021–2026 — lihat [§9](#9-paper-referensi)), diringkas di `documentation/research/recommendations.md`.

| Tahap | Model | Lisensi | Alasan Dipilih |
|---|---|---|---|
| **Deteksi + landmark** | SCRFD (kandidat produksi) / **MediaPipe Face Landmarker** (dipakai saat ini untuk QC pipeline) | SCRFD: kode MIT, *weights* non-komersial (perlu lisensi/retrain); MediaPipe: Apache-2.0, gratis | SCRFD unggul akurasi/latensi untuk deteksi produksi; MediaPipe dipakai di `ai-training` karena model asetnya gratis-didistribusikan tanpa isu lisensi dan cukup untuk quality-check landmark |
| **Liveness / Anti-Spoofing** | MiniFASNet (Silent-Face) | Apache-2.0 | Model FAS *single-frame* ringan (sub-ms), harus **di-fine-tune ulang** dengan data serangan print/replay dari kamera pintu sendiri — literatur menunjukkan performa akademik FAS tidak transfer lintas domain kamera |
| **Ekstraksi fitur (embedding)** | AdaFace (IR-50/IR-101, 512-d) | Repo MIT | *Quality-adaptive margin* — paling tahan terhadap frame blur/pose ekstrem, persis kondisi video enrollment 360° dan kamera CCTV pintu (bukan foto studio) |
| **Pencocokan** | Cosine similarity, *max-fusion* multi-template per posisi jam | — | Video 360° menghasilkan banyak sudut pandang wajah → disimpan sebagai beberapa template per identitas (bukan 1), skor akhir = kemiripan tertinggi terhadap salah satu template (memaksimalkan Recall) |

**Keputusan lisensi (dicatat 2026-08-30):** Aplikasi ini **tidak diperjualbelikan** — dipakai internal organisasi. Risiko lisensi *non-commercial* pada *weights* SCRFD/InsightFace diterima secara sadar oleh pemilik proyek; jalur mitigasi (retrain dari kode MIT, atau data sintetis DCFace/Vec2Face+) tetap tersedia bila kelak diperlukan.

### 8.4 Fine-Tuning: Pendekatan yang Dipilih (dan yang Sengaja Dihindari)

**Keputusan tegas: *gallery-based embedding matching*, BUKAN fine-tuning model per identitas.**

| Aspek | Embedding Matching (dipilih) | Fine-Tuning per Identitas (dihindari) |
|---|---|---|
| Recall | Tinggi bila galeri multi-pose — justru keunggulan capture 360° kita | Naik marginal, berisiko *overfit* ke kondisi video enrollment |
| Operasional | Enroll/revoke = insert/delete vektor, instan | Perlu retrain tiap ada perubahan user (GPU job + QA regresi ulang) |
| Skalabilitas | Ribuan identitas, pencocokan < 1 ms | Model membengkak per identitas; *catastrophic forgetting* |
| Stabilitas Precision/F1 | Threshold global terkendali | Distribusi skor bergeser tiap retrain, threshold harus dikalibrasi ulang |

**Fine-tuning yang MASIH relevan (fase 2, opsional):** *domain fine-tuning* satu kali pada backbone AdaFace (bukan per identitas) memakai gabungan data kamera pintu sungguhan + data sintetis (mis. DCFace/Vec2Face+), untuk menutup *domain gap* pencahayaan/sudut kamera — ini menaikkan Recall tanpa menambah biaya operasional per pengguna. Alur pelatihannya (di `ai-training/`):

```mermaid
sequenceDiagram
    participant T as Trigger (jadwal / N enrollment baru / manual)
    participant P as ai-training pipeline
    participant S as S3 (dataset + artifact)
    participant M as MLflow
    participant H as Manusia (ML Engineer/Admin)
    participant W as Worker Re-embed
    participant I as Inference

    T->>P: Mulai job training
    P->>S: Bangun dataset snapshot (manifest, ber-versi)
    P->>P: Preprocessing, augmentasi, fine-tune (GPU)
    P->>M: Log parameter & metrik (Recall, F1, Precision, latency_ms)
    P->>M: Daftarkan model sebagai CANDIDATE
    H->>M: Tinjau gate — Recall tidak boleh turun DAN anggaran latensi terpenuhi
    H->>M: Setujui → promosikan ke PRODUCTION
    M-->>W: Event model versi baru
    W->>S: Re-embed seluruh galeri dengan model baru
    W->>I: Ganti atomik {versi model, versi galeri} (blue/green)
```

Promosi model **selalu** butuh persetujuan manusia (*human-in-the-loop*) — tidak pernah otomatis, karena ini sistem access control fisik.

### 8.5 Metrik Evaluasi & Threshold

- **Urutan prioritas metrik**: **Recall** (utama) → **F1** → **Precision**, plus **latensi (ms)** sebagai metrik operasional.
- **Formulasi**: *open-set 1:N identification*. Recall = 1 − FNIR (*False Negative Identification Rate*).
- **Cara menetapkan threshold τ**: tetapkan dulu **anggaran keamanan** dari sisi FPIR (*False Positive Identification Rate*, mis. ≤1%), lalu pilih τ **terkecil** yang masih memenuhi anggaran itu → Recall dimaksimalkan **di bawah kendala keamanan** (bukan tanpa batas — Recall 100% dengan τ=0 berarti pintu terbuka untuk siapa saja).
- **Target v1**: Recall ≥ 0,98 pada FAR ≤ 0,1%.
- **Multi-frame voting**: di pintu, evaluasi 3–5 frame berurutan, terima bila ≥2 frame lolos τ — menaikkan Recall tanpa menambah risiko *false accept* dari satu frame buruk.
- **Evaluasi**: benchmark internal beku (probe genuine + impostor dari kondisi pintu nyata, bukan dataset publik), dijalankan otomatis di setiap kandidat model sebelum promosi.

---

## 9. Paper Referensi

Riset lengkap (±55 paper, dengan tabel relevansi per topik) ada di [`documentation/research/literature-review.md`](documentation/research/literature-review.md) (tidak di-commit — internal tim). Daftar di bawah adalah subset paper paling berpengaruh terhadap keputusan desain di atas, format IEEE.

### Loss Function & Backbone Recognition

[1] J. Deng, J. Guo, N. Xue, and S. Zafeiriou, "ArcFace: Additive Angular Margin Loss for Deep Face Recognition," in *Proc. IEEE/CVF Conf. Computer Vision and Pattern Recognition (CVPR)*, 2019, pp. 4690–4699.

[2] H. Wang *et al.*, "CosFace: Large Margin Cosine Loss for Deep Face Recognition," in *Proc. IEEE/CVF Conf. Computer Vision and Pattern Recognition (CVPR)*, 2018, pp. 5265–5274.

[3] Q. Meng, S. Zhao, Z. Huang, and F. Zhou, "MagFace: A Universal Representation for Face Recognition and Quality Assessment," in *Proc. IEEE/CVF Conf. Computer Vision and Pattern Recognition (CVPR)*, 2021, pp. 14225–14234.

[4] M. Kim, A. K. Jain, and X. Liu, "AdaFace: Quality Adaptive Margin for Face Recognition," in *Proc. IEEE/CVF Conf. Computer Vision and Pattern Recognition (CVPR)*, 2022, pp. 18750–18759.

[5] M. Kim, Y. Su, F. Liu, A. K. Jain, and X. Liu, "KeyPoint Relative Position Encoding for Face Recognition," in *Proc. IEEE/CVF Conf. Computer Vision and Pattern Recognition (CVPR)*, 2024.

[6] J. Dan, Y. Liu, H. Xie, J. Deng, H. Xie, X. Xie, and B. Sun, "TransFace: Calibrating Transformer Training for Face Recognition from a Data-Centric Perspective," in *Proc. IEEE/CVF Int. Conf. Computer Vision (ICCV)*, 2023.

[7] "Unified Cross-Entropy Loss for Deep Face Recognition (UniFace)," in *Proc. IEEE/CVF Int. Conf. Computer Vision (ICCV)*, 2023.

### Face Detection & Alignment

[8] J. Deng, J. Guo, E. Ververas, I. Kotsia, and S. Zafeiriou, "RetinaFace: Single-Shot Multi-Level Face Localisation in the Wild," in *Proc. IEEE/CVF Conf. Computer Vision and Pattern Recognition (CVPR)*, 2020, pp. 5203–5212.

[9] J. Guo, J. Deng, A. Lattas, and S. Zafeiriou, "Sample and Computation Redistribution for Efficient Face Detection (SCRFD)," in *Proc. Int. Conf. Learning Representations (ICLR)*, 2022. arXiv:2105.04714.

### Pose-Invariant / Multi-View Recognition & Template Aggregation

[10] M. Kim, F. Liu, A. K. Jain, and X. Liu, "Cluster and Aggregate: Face Recognition with Large Probe Set (CAFace)," in *Proc. Advances in Neural Information Processing Systems (NeurIPS)*, 2022.

[11] D. Kim *et al.*, "FaceCoresetNet: Differentiable Coresets for Face Set Recognition," in *Proc. AAAI Conf. Artificial Intelligence*, 2024.

[12] W. AbdAlmageed *et al.*, "A Comprehensive Survey on Pose-Invariant Face Recognition," *ACM Trans. Intelligent Systems and Technology*, 2016.

### Anti-Spoofing / Liveness Detection

[13] Z. Yu, Y. Qin, X. Li, C. Zhao, Z. Lei, and G. Zhao, "Deep Learning for Face Anti-Spoofing: A Survey," *IEEE Trans. Pattern Analysis and Machine Intelligence (TPAMI)*, 2022.

[14] Y. Sun *et al.*, "Rethinking Domain Generalization for Face Anti-Spoofing: Separability and Alignment (SAFAS)," in *Proc. IEEE/CVF Conf. Computer Vision and Pattern Recognition (CVPR)*, 2023.

[15] K. Srivatsan, M. Naseer, and K. Nandakumar, "FLIP: Cross-Domain Face Anti-Spoofing with Language Image Pretraining," in *Proc. IEEE/CVF Int. Conf. Computer Vision (ICCV)*, 2023.

[16] "minivision-ai/Silent-Face-Anti-Spoofing (MiniFASNet)," GitHub repository, Apache-2.0 License. [Online]. Available: https://github.com/minivision-ai/Silent-Face-Anti-Spoofing

### Model Ringan & Optimasi Latensi Inference

[17] K. George, C. Ecabert, H. O. Shahreza, K. Kotwal, and S. Marcel, "EdgeFace: Efficient Face Recognition Model for Edge Devices," *IEEE Trans. Biometrics, Behavior, and Identity Science (TBIOM)*, 2024.

[18] Y. Boutros, N. Damer, and A. Kuijper, "QuantFace: Towards Lightweight Face Recognition by Synthetic Data Low-Bit Quantization," in *Proc. Int. Conf. Pattern Recognition (ICPR)*, 2022.

### Face Image Quality Assessment (FIQA) & Seleksi Frame

[19] P. Terhorst, J. N. Kolf, N. Damer, F. Kirchbuchner, and A. Kuijper, "SER-FIQ: Unsupervised Estimation of Face Image Quality Based on Stochastic Embedding Robustness," in *Proc. IEEE/CVF Conf. Computer Vision and Pattern Recognition (CVPR)*, 2020.

[20] F. Boutros, M. Fang, M. Klemt, B. Fu, and N. Damer, "CR-FIQA: Face Image Quality Assessment by Learning Sample Relative Classifiability," in *Proc. IEEE/CVF Conf. Computer Vision and Pattern Recognition (CVPR)*, 2023.

### Enrollment Few-Shot, Open-Set Identification & Data Sintetis

[21] M. Kim, F. Liu, A. K. Jain, and X. Liu, "DCFace: Synthetic Face Generation with Dual Condition Diffusion Model," in *Proc. IEEE/CVF Conf. Computer Vision and Pattern Recognition (CVPR)*, 2023.

[22] "Open-Set Face Identification on Few-Shot Gallery by Fine-Tuning," in *Proc. Int. Conf. Pattern Recognition (ICPR)*, 2022. arXiv:2301.01922.

[23] InsightFace, "Choose a Face Recognition Model and Evaluate Threshold (1:1 vs 1:N Guide)." [Online]. Available: https://www.insightface.ai/guides/choose-face-recognition-model-and-evaluate

---

Daftar lengkap ±55 paper (termasuk yang tidak dikutip di atas: UniTSFace, TopoFR, SwinFace, YOLO5Face, PoseFace, CoNAN, FM-ViT, S-Adapter, CFPL-FAS, GhostFaceNets, MixFaceNets, SynthDistill, ViT-FIQA, TransFIRA, IDiff-Face, Vec2Face/Vec2Face+, HyperFace, dan lain-lain) beserta relevansi masing-masing terhadap keputusan desain proyek ada di `documentation/research/literature-review.md` dan `documentation/research/recommendations.md`.

---

## Workflow Kontribusi

Branch dari `master`: `features/<nama_fitur>` atau `bugfix/<nama_bug>` → implementasi → **QA harus PASSED** → buka Pull Request → CI (lint+test per service, path-filtered) harus hijau → merge → `graphify update .` → bump versi (`minor` untuk fitur, `patch` untuk bugfix) + tag. Detail lengkap: `CLAUDE.md` (internal, tidak di-commit).
