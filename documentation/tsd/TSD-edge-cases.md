# TSD — Edge-Case Robustness (Access Control + Absensi)

> Technical Specification Document — addendum terpisah dari `TSD.md` (konsolidasi belakangan setelah review).
> Status: **FINAL v0.2** (siap task breakdown PM) · Penulis: System Analyst · Tanggal: 2026-09-01
> Basis requirement: `documentation/research/papers/edge-cases/recommendations-edge-cases.md` (selanjutnya **REC**) + `literature-review-edge-cases.md`.
> Review riset: `documentation/research/papers/edge-cases/design-review-answers.md` (selanjutnya **REV**) — semua OQ terjawab, revisi R-1..R-4 terintegrasi.
> Referensi arsitektur: `documentation/tsd/TSD.md`, `documentation/fsd/FSD-AI.md`.
> Audiens: Project Manager (task breakdown per agent: ai-engineer / backend-engineer / frontend-engineer / qa-engineer).

**Changelog v0.2 (dari v0.1, hasil review AI Researcher):**
- §6 "Open Questions" → §6 "Keputusan Desain (resolusi OQ-1..OQ-10)" — semua pertanyaan terjawab & mengikat.
- **R-1**: + **D-4.5** job backfill template masked untuk user legacy (masuk Gelombang 1).
- **R-2**: D-3/C-6 dipertegas — **liveness selalu dievaluasi pada frame RAW**; frame hasil SCI hanya untuk deteksi(+alignment/embedding sesuai kalibrasi).
- **R-3**: D-6 guard adaptive-template diperkuat jadi **4 syarat**; ASM-EC-09 direvisi (classifier 3-kelas = desain utama, landmark-confidence hanya sinyal sekunder).
- **R-4**: D-7 + slice interaksi masked×demografi, + benchmark PAD beku formal (test split OQ-2) dengan gate BPCER@APCER; D-3/C-1 + kriteria kelulusan log-only→enforcing.
- OQ-6: sumber threshold direvisi — **default per-mode = metadata artefak model di MLflow; `recognition_configs` = override kebijakan** (D-2, D-4.2).
- OQ-10: C-5 memakai **`capture_session_id` client-generated** (kontrak `/recognize` additive), bukan tracker stateful server-side.
- ASM-EC-04/07/09/11/12 diperbarui; D-9 diperbarui (backfill di Gelombang 1).

**Update pasca-final (2026-09-01, keputusan PM/user atas open items task-breakdown — tanpa bump versi dokumen):**
- **D-8**: lokasi `camera-placement-guide.md` DIPUTUSKAN — Opsi B, `documentation/operations/` (tidak di-commit, konsisten pola `planning/`/`research/`). Bukan lagi open item.
- **ASM-EC-06**: retensi `template_candidates` DIPUTUSKAN **final 90 hari** (bukan draft 30 hari) — disamakan dengan retensi media enrollment (ASM-10) untuk konsistensi kebijakan retensi.
- **ASM-EC-05**: konfirmasi final — consent DIPERLUAS lewat mekanisme versioning existing (`consents.consent_version`, append record baru per bump versi; lihat `backend/app/models/consent.py`, `backend/app/repositories/consents.py`), BUKAN tabel/consent terpisah. Task implementasi: lihat `task-breakdown.md` §"Keputusan Susulan" (EC-BE-09/EC-FE-05).
- **Scope IN §1 butir 5** (UI capture enrollment & UI operasional): DIKONFIRMASI mencakup juga **dialog konfirmasi tambahan untuk high-similarity pair** (D-4.4) sebagai bagian pipeline recognition — dibatasi HANYA layar konfirmasi (PIN/re-scan/manual), BUKAN fitur absensi end-to-end (jadwal kerja/rekap/HRIS tetap Scope OUT, tidak berubah). Task implementasi: `task-breakdown.md` §"Keputusan Susulan" (EC-BE-10/EC-FE-06/EC-QA-05).

---

## 1. Ringkasan Eksekutif & Scope

Sistem existing (enrollment 360° → QC → embedding AdaFace → gallery pgvector → `/recognize` dengan liveness MiniFASNet + temporal voting) sudah memiliki fondasi yang tepat, tetapi **belum meng-cover edge case** yang diidentifikasi riset: masker, low-light, kacamata, occlusion, aging/drift, blur, low-res/domain-gap kamera, multi-wajah antrian, bias demografi, dan kembar identik. Modul ini direncanakan dipakai juga untuk **ABSENSI**, yang menggeser profil risiko: Recall lebih ditekan (karyawan sah gagal absen = insiden harian), sementara salah-catat identitas (Precision) tetap fatal untuk absensi.

**Temuan gap utama (ringkas):**

- **A. UI capture enrollment**: capture existing = 1 foto frontal + 1 video webm 10–30 dtk (12 posisi jam, yaw+pitch). **Cukup sebagai baseline**, tetapi TIDAK meng-capture varian kondisi (kacamata on/off) dan backend TIDAK punya cara menandai varian media/template. Strategi yang diusulkan: **capture tambahan minimal (hanya varian kacamata, opsional) + augmentasi sintetis untuk sisanya (masker MLFW-style, occlusion OCFR-style)** — durasi enrollment hampir tidak bertambah.
- **B. Trigger training**: yang ada hari ini hanya **job EVALUASI** (`POST /training/jobs` → `run_training_evaluation_job`) + CLI snapshot/eda/evaluate. **Fine-tuning belum terimplementasi** (`run_finetune_job` = `NotImplementedError`), tidak ada jenis job fine-tune di API, tidak ada opsi augmentasi, tidak ada job fine-tune liveness. Perlu perluasan skema `training_jobs` + task Celery baru.

**Scope IN:**
1. Perubahan skema DB (flag varian media, flag template masked/recent, threshold per-mode/per-device, pasangan high-similarity).
2. Perubahan kontrak API high-level (presign varian, training job types, config threshold, funnel logging).
3. Desain pipeline inference edge-case path (gate murah, deteksi masker, threshold multi-mode, zona absensi, tie-break).
4. Desain job training baru (fine-tune AdaFace augmentasi gabungan, fine-tune MiniFASNet).
5. Perubahan UI capture enrollment (langkah varian kacamata, protokol matched-condition) & UI operasional.
6. Kebijakan operasional kamera (dokumen panduan, bukan kode).

**Scope OUT (eksplisit):**
- Fitur absensi end-to-end (jadwal kerja, rekap jam, integrasi HRIS) — dokumen ini hanya menyiapkan pipeline recognition agar layak dipakai absensi; produk absensi = FSD terpisah.
- Long-term items REC: kamera RGB-IR (1.6), EUM/SRT (4.6), Retinexformer GPU (1.3) — dicatat sebagai backlog LT, tidak didesain di sini.
- Perubahan arsitektur besar (Qdrant, Rust rewrite).

---

## 2. Jawaban A — Gap Analysis UI Capture Enrollment

### 2.1 Apa yang SUDAH di-capture hari ini (bukti kode)

Sumber: `frontend/src/features/enrollment-capture/EnrollmentCapturePage.tsx`, `types.ts`; `backend/app/schemas/media.py`; `backend/app/models/media_object.py`, `face_embedding.py`.

> **Catatan (snapshot).** Tabel di bawah adalah gap analysis pada saat dokumen
> ini ditulis dan sengaja TIDAK di-rewrite, karena butir-butir rencana
> (A-1..A-5) di bawahnya mereferensikan kondisi awal ini. Dua baris sudah
> tidak berlaku lagi sejak ditulis:
> - **Kontrak presign** kini punya `variant`
>   (`default|no_glasses|glasses|pitch_ext`, EC-BE-02) dan `clock_position`
>   (1..12, migrasi `e4b9d2f6a8c3`).
> - **Media yang di-capture / skema `media_objects`** — video `rotation.webm`
>   sedang digantikan **foto per posisi jam** (`photo_pos_{PP}_{k}.jpg`,
>   ditandai kolom `clock_position`). Video tetap diterima untuk session
>   legacy; lihat TSD.md §2.1 dan §7.

| Aspek | Kondisi aktual | Bukti |
|---|---|---|
| Media yang di-capture | **1 foto frontal JPEG (quality 0.92)** + **1 video `video/webm`** | `EnrollmentCapturePage.tsx:171-181` (`canvas.toBlob('image/jpeg', 0.92)`), `:211` (`MediaRecorder(stream, { mimeType: 'video/webm' })`) |
| Resolusi | Kamera diminta **1280×720 @30fps (ideal)**; canvas mengikuti `videoWidth/Height` aktual | `EnrollmentCapturePage.tsx:105-107` |
| Durasi video | **Min 10 dtk, max 30 dtk** (auto-stop di 30) | `EnrollmentCapturePage.tsx:34-35, 218-224, 425` |
| Coverage pose | 12 posisi jam (yaw+pitch orientasi kepala, ASM-03 terkoreksi); tombol Selesai terkunci sampai 12/12 sektor `done` | `types.ts:10-20`, `EnrollmentCapturePage.tsx:79, 425` (`canFinishVideo`) |
| Quality gate client-side | Blur (variance-of-Laplacian) + brightness (mean gray) per sampel 150 ms | `types.ts:38-52`, `imageQuality.ts`, `SAMPLE_INTERVAL_MS=36` |
| Varian kondisi (masker/kacamata/lighting/ekspresi) | **TIDAK ADA** — wizard hanya 1 pass: consent → preflight → video → review → upload | `EnrollmentCapturePage.tsx:26-32` (WizardStep union) |
| Kontrak presign | `kind` **hanya `Literal["photo","video"]`** + content_type/size/sha256 — tidak ada field varian/label | `backend/app/schemas/media.py:23-26`; frontend `types.ts:64-71` |
| Skema `media_objects` | Kolom: session_id, `kind` (enum `photo|video|event_frame`), s3 loc, checksum, size, content_type, status, retention — **tidak ada kolom variant/label** | `backend/app/models/media_object.py:15-59`, `enums.py:43-46` |
| Skema `face_embeddings` | user_id, session_id, model_version, **`pose_bucket` (string posisi jam saja)**, vector(512) — **tidak ada flag `masked`, `variant`, atau `template_kind`** | `backend/app/models/face_embedding.py:22-42` |
| Ekstraksi template | Worker QC mengekstrak embedding per pose bucket dari video; tidak ada generasi varian sintetis | `ai-training/src/ai_training/worker/tasks.py:312-338` (`extract_gallery_embeddings`) |

### 2.2 Verdict: cukup atau kurang?

**Cukup sebagai baseline pose-coverage; KURANG untuk edge-case coverage.** Secara spesifik terhadap rekomendasi riset:

| Kebutuhan REC | Terpenuhi capture existing? | Keterangan |
|---|---|---|
| REC 2.1 — varian kacamata on/off | ❌ | Tidak ada langkah capture kedua; skema tidak bisa menandainya |
| REC 4.4 — template masked di gallery | ❌ (tapi TIDAK butuh capture) | Bisa digenerate sintetis dari frame terbaik; blocker-nya skema (flag `masked`) bukan UI |
| REC 3 (matched-condition: hijab, kacamata permanen, jenggot) | ✅ sebagian | Video existing merekam kondisi apa adanya; yang kurang hanyalah **instruksi eksplisit** "tampil seperti Anda datang bekerja" di layar consent/preflight |
| REC 8.2 — pose-bin pitch (kamera tinggi) | ✅ sebagian | 12 posisi jam sudah mengandung pitch (jam 12 = mendongak, jam 6 = menunduk, `types.ts:10`); pitch EKSTREM (>30° dari atas) tidak ter-cover — sengaja dijadikan opsional (lihat 2.3) |
| Multi-kondisi pencahayaan | ❌ (dan diputuskan TIDAK dicapture) | Ditangani augmentasi brightness/gamma saat fine-tune (REC 1.5) + operasional fill-light; capture multi-lighting menambah durasi & kompleksitas UX tanpa nilai sebanding |
| Ekspresi | ✅ tidak perlu | REC §7: ekspresi = masalah frame-level di inference (temporal voting), bukan masalah data enrollment |
| Re-enrollment berkala / aging | ❌ | Tidak ada mekanisme; ditangani kebijakan re-enroll + adaptive template (REC 6.1/6.2), bukan langkah capture |

### 2.3 Fitur yang diusulkan (A-1 … A-5)

Prinsip trade-off: **enrollment existing ±60–90 dtk; setiap penambahan wajib < +30 dtk.** Augmentasi sintetis dipilih di semua tempat yang riset katakan setara/lebih baik dari capture riil (masker: resep juara MFR 2021; occlusion: protokol OCFR) — capture riil hanya untuk varian yang sintetis tidak bisa tiru dengan baik (melepas kacamata mengubah geometri wajah riil + menghilangkan distorsi lensa).

| ID | Fitur | Deskripsi | Dampak UX |
|---|---|---|---|
| **A-1** | Langkah capture "varian kacamata" (kondisional) | Setelah video 360°, wizard bertanya "Apakah Anda sehari-hari memakai kacamata?" → jika ya: **1 foto frontal tambahan tanpa kacamata** (atau sebaliknya bila enrollment dilakukan tanpa kacamata). Bukan video kedua — 1 foto cukup untuk 1–2 template frontal varian (REC 2.1 menyebut "2 set template"; template pose non-frontal varian-kacamata dinilai tidak sepadan biayanya → ASM-EC-03). | +10–15 dtk, hanya untuk user berkacamata |
| **A-2** | Instruksi matched-condition | Teks consent/preflight ditambah: "Tampil seperti Anda datang bekerja sehari-hari (hijab, kacamata, jenggot seperti biasa). Lepaskan masker dan sunglasses selama perekaman." + checklist preflight menolak wajah ber-masker/sunglasses (pakai deteksi masker C-2 yang sama, dijalankan client-side bila memungkinkan, else validasi di QC server). | +0 dtk |
| **A-3** | Pitch ekstrem opsional (flag konfigurasi) | Langkah tambahan di akhir video: "menunduk lebih dalam, lalu mendongak" (2–3 dtk) → pose bucket `pitch_down_deep`/`pitch_up_deep`. **Dinonaktifkan by default**; diaktifkan per-deployment hanya bila kamera terpasang tinggi (REC 8.1 tetap solusi utama: kamera setinggi wajah). | +2–3 dtk bila aktif |
| **A-4** | Generasi template sintetis saat QC/embedding (tanpa UI) | Worker TR-02/03 (`ai-training/worker/tasks.py::run_enrollment_qc_core`) ditambah langkah: generate varian masker sintetis dengan **MaskTheFace (github.com/aqeelanwar/MaskTheFace, lisensi MIT; dependensi dlib = Boost License — keputusan OQ-1/REV, dipilih di atas tool MLFW asli yang tanpa lisensi jelas)**. Spesifikasi: **2 tipe masker (surgical biru/putih + kain gelap), full-coverage menutup hidung** (variabel dominan = coverage hidung, NIST IR 8311); frame sumber = frame terbaik pose **frontal + ±30° yaw** → **2–3 embedding `synthetic_masked`/user** (pose profil tidak berguna — probe bermasker hampir selalu frontal-ish). CPU-only, puluhan ms/gambar, offline di worker. Occlusion/kacamata sintetis TIDAK jadi template (hanya augmentasi training, REC 2.2/5.3). User legacy dicover job backfill **D-4.5**. | +0 dtk (server-side) |
| **A-5** | Kebijakan re-enrollment (tanpa capture baru) | Query terjadwal (Celery beat, backend): user dengan enrollment > 24 bulan ATAU moving-average skor genuine < τ+margin (dari log funnel D-1) → tandai `reenroll_due`, tampilkan di UI manajemen enrollment (REC 6.2). Enrollment ulang memakai wizard existing. | +0 dtk |

### 2.4 Perubahan kontrak backend untuk A (high-level)

1. **`media_objects` + kolom `variant`** (nullable string enum: `default` | `no_glasses` | `glasses` | `pitch_ext`); `PresignRequest` + field opsional `variant` (default `default`). Additive, backward-compatible.
2. **`face_embeddings` + kolom `masked boolean NOT NULL DEFAULT false`** dan **`template_kind`** (enum: `enrolled` | `synthetic_masked` | `recent`) — `recent` dipakai desain D-6 (adaptive update). `pose_bucket` diperluas nilainya (tetap string, tidak perlu migrasi tipe: `backend/app/models/face_embedding.py:38` sudah `String(16)`).
3. **QC report** (`enrollment_sessions.qc_report` jsonb) + field ringkasan varian yang diterima (`variants_captured`, `synthetic_templates_generated`) — jsonb, tanpa migrasi.

---

## 3. Jawaban B — Gap Analysis Trigger Training

### 3.1 Yang SUDAH ada (bukti kode)

| Mekanisme | Kondisi aktual | Bukti |
|---|---|---|
| `POST /training/jobs` (manual, dari UI Models & Training) | Ada, ADMIN-only; **parameter hanya `model_version` + `benchmark_id`** | `backend/app/routers/training.py:72-88`; `backend/app/schemas/training.py:12-14` |
| Isi job yang didispatch | **EVALUASI SAJA** — `run_training_evaluation_job` menjalankan `evaluate_candidate` (benchmark beku) lalu menulis metrik ke `models` | `ai-training/src/ai_training/worker/tasks.py:408-490` |
| Fine-tuning | **Belum terimplementasi**: `run_finetune_job` = `NotImplementedError("Fine-tuning lands with TR-06.")`; CLI `finetune --snapshot-id` terdaftar tapi jatuh ke stub "not implemented yet" | `ai-training/src/ai_training/training/finetune.py:15-17`; `cli.py:39-40, 125-127` |
| Trigger otomatis/terjadwal | **Tidak ada** — dicatat eksplisit "Automatic triggering (TR-09) is out of scope here" | `backend/app/routers/training.py:79-80` |
| Dataset snapshot | Ada via CLI `snapshot --filter key=value` (keys: `external_ref, created_after, created_before, kind`) — **tidak bisa filter by variant/kondisi**, dan tidak terhubung ke `POST /training/jobs` | `cli.py:27-34, 61-68`; `ai_training/data/snapshots.py` |
| Job gallery re-embed | Ada (`run_gallery_reembed_job`, dispatched pasca-promote) | `ai-training/src/ai_training/worker/tasks.py:626-687` |
| Fine-tune liveness (MiniFASNet) | **Tidak ada sama sekali** — `ai_training/liveness/` hanya berisi detector inference-side | `ai-training/src/ai_training/liveness/detector.py`, `minifasnet_net.py` |
| Skema `training_jobs` | Tidak ada kolom `job_type`, `snapshot_id`, maupun `config/params` | `backend/app/schemas/training.py:17-29` (response fields = id, model_version, benchmark_id, status, triggered_by, timestamps, error, mlflow_run_id) |

### 3.2 Verdict

**Kurang.** Untuk kebutuhan edge-case fine-tuning tidak ada satu pun jalur eksekusi: (a) tidak ada jenis job selain evaluasi, (b) tidak ada tempat menaruh konfigurasi augmentasi, (c) snapshot tooling tidak bisa menyusun dataset per-kondisi (masked/low-light/berlensa), (d) tidak ada pipeline data liveness (bona fide + spoof bermasker/low-light) sama sekali.

### 3.3 Penambahan yang diusulkan (B-1 … B-5)

| ID | Penambahan | Detail |
|---|---|---|
| **B-1** | `training_jobs.job_type` + `params jsonb` | Enum job_type: `EVALUATION` (existing, default lama), `FINETUNE_EMBEDDER`, `FINETUNE_LIVENESS`, `GALLERY_REEMBED` (formalisasi TR-08 agar punya status API — menutup scope cut yang dicatat di `tasks.py:660-668`), **`BACKFILL_MASKED_TEMPLATES` (D-4.5, R-1)**. `params` jsonb memuat konfigurasi per-type (lihat B-2/B-3). `TrainingJobCreateRequest` diperluas: `job_type`, `snapshot_id?`, `params?`; `model_version`/`benchmark_id` jadi opsional per-type. Additive + backfill `job_type='EVALUATION'`. |
| **B-2** | Job `FINETUNE_EMBEDDER` (TR-06 + augmentasi gabungan) | Implementasi `run_finetune_job` sebagai task Celery `run_finetune_embedder_job`. `params.augmentations` = daftar toggle+intensitas: `mask_mlfw`, `occlusion_ocfr`, `multi_resolution`, `alignment_perturb_aroface`, `brightness_gamma` (REC 4.3/5.3/10.2/8.3/1.5 — **satu job yang sama**, sesuai REC prioritas #7). Output: model CANDIDATE di MLflow → gate evaluasi existing (`evaluate_candidate`) → promote gate existing tidak berubah. |
| **B-3** | Job `FINETUNE_LIVENESS` (MiniFASNet) | Task baru; input `params.dataset_ref` menunjuk dataset PAD lokal. **Spesifikasi dataset minimum (keputusan OQ-2/REV, acuan CRMA/Fang 2021)**: **≥30 subjek bona fide (ideal 50–80), subject-disjoint**; per subjek 4 klip ±5 dtk (2 kondisi cahaya {normal, dark} × masker {on, off}); attack: ≥3 media print + ≥3 device replay, tiap instrument × {unmasked, **masked-attack tipe AM1/AM2 Fang — AM2 (masker riil ditempel pada print/replay) WAJIB ada**} × {normal, dark}. **Protokol**: split 3-way subject-disjoint ±60/20/20; fine-tune freeze layer awal + LR rendah + class-balanced + early-stop pada val lintas-kondisi; kalibrasi threshold per mode {normal, masked, dark} di **val** dengan budget APCER (≤5% akses / ≤10% absensi) → laporkan BPCER@APCER di **test** (tidak pernah kalibrasi di test). Output: model liveness CANDIDATE + **map `{mode: threshold}` + kurva sebagai METADATA ARTEFAK di MLflow** (keputusan OQ-6 — satu paket dengan weights); test split disimpan sebagai benchmark PAD beku (D-7.4). Registry: kolom `models.model_kind` (`embedder`\|`liveness`); gate promosi liveness = BPCER@APCER per mode (bukan Recall/F1 identifikasi). |
| **B-4** | Snapshot tooling: filter kondisi + sumber PAD | `snapshot --filter` ditambah keys: `variant` (join ke `media_objects.variant` baru), `condition` (dari flag kondisi event, D-1), `source` (`enrollment` \| `event_frame`). Snapshot manifest tetap manifest-only di S3 (pola existing). Untuk PAD: konvensi prefix S3 baru `s3://frac-media/pad/{collection_id}/...` + skrip upload operator (bukan jalur enrollment; media PAD bukan milik satu user). |
| **B-5** | Trigger terjadwal & event-driven (TR-09 diformalkan) | Celery beat: (a) evaluasi berkala model PRODUCTION pada benchmark edge-case (D-7) — deteksi drift; (b) trigger "N enrollment baru sejak fine-tune terakhir" → notifikasi (BUKAN auto-run; ASM-EC-08: semua job training tetap human-triggered, konsisten dengan gate FR-TRN-05). |

---

## 4. Desain per Rekomendasi Riset

Notasi komponen: FE = `frontend/`, BE = `backend/`, TRN = `ai-training/`, INF = `ai-inference/`.

### D-1. Logging funnel per-stage + flag kondisi (REC 14.1) — **PONDASI, kerjakan pertama**

- **Komponen**: INF (`pipeline/recognize.py`, `events.py`), BE (`access_events` + schema), FE (dashboard monitoring).
- **Desain**: setiap keputusan `/recognize` membawa: skor liveness per frame, skor matching top1/top2, dan `condition_flags jsonb` (`masked`, `dark` (mean-luma < ambang), `blurry` (VoL < ambang), `low_res` (bbox < 80px), `sunglasses`), plus `reject_stage` (`detection|liveness|quality_gate|threshold|policy`). `access_events` existing sudah punya `similarity`, `liveness_score`, `latency_ms` (TSD §4) → **migrasi additive**: + `condition_flags jsonb`, + `reject_stage`, + `device_class` (D-5). INF `RecognitionResult` diperluas.
- **Dependency**: tidak ada — semua desain lain (kalibrasi τ, re-enroll trigger, audit bias) membaca log ini. 
- **Impact**: privasi — flag kondisi bukan biometrik tambahan, tapi tetap data perilaku → masuk cakupan retensi/audit existing. Latensi ~0 (fire-and-forget existing). Risiko regresi rendah (additive).

### D-2. Liveness fine-tune + threshold liveness per-mode (REC 4.1, 1.4, 14.2)

- **Komponen**: TRN (job B-3, pipeline data PAD), INF (`config.py`, pipeline), BE (registry `model_kind`, config API).
- **Desain**: 
  1. Koleksi data PAD lokal (bona fide bermasker/low-light + print/replay attack direkam kamera deployment) → B-4 prefix `pad/`.
  2. Job `FINETUNE_LIVENESS` (B-3) → kandidat + kurva BPCER@APCER per mode.
  3. INF: `liveness_threshold` tunggal (`ai-inference/config.py:75`, placeholder 0.5 belum dikalibrasi — dicatat sendiri di komentarnya) → **map `{mode: threshold}`** dengan mode = fungsi flag kondisi frame (`masked`, `dark`, `normal`). **Sumber nilai (keputusan OQ-6/REV): default per-mode disimpan sebagai METADATA ARTEFAK MODEL di MLflow** (hasil kalibrasi job B-3, satu paket dengan weights — rollback model otomatis me-rollback threshold, atomik); INF membacanya via cache registry (pola `ProductionVersionCache` existing). `recognition_configs` (D-5) hanya menyimpan **override/delta kebijakan** (per device_class, budget APCER absensi vs akses, kill-switch mode). Resolusi runtime: `artefak.default[mode]` → override `recognition_configs[(device_class, mode)]` bila ada.
  4. **Budget APCER awal per mode (OQ-2/REV): ≤5% akses, ≤10% absensi**; kalibrasi di val split, laporan BPCER@APCER di test split (subject-disjoint, tidak pernah kalibrasi di test).
  5. **Frame input liveness (R-2)**: skor liveness SELALU dihitung dari frame RAW — lihat C-6 di D-3. Kalibrasi threshold mode `dark` dilakukan pada distribusi input yang identik dengan produksi.
- **Dependency**: D-1 (flag kondisi) → B-3 → kalibrasi → metadata artefak. Deteksi masker (C-2 di D-3) prasyarat mode `masked`.
- **Impact**: keamanan — melonggarkan threshold liveness mode masked menaikkan risiko spoof bermasker; mitigasi: budget APCER per mode ditetapkan eksplisit saat kalibrasi, [AKSES] tidak pernah memakai `liveness_soft_fail` (REC 14.3 hanya [ABSENSI], di-gate per-device-class). Latensi 0 ms. **Regresi tertinggi di antara semua desain** (mengganti model liveness) → wajib benchmark PAD beku (formal di D-7, test split OQ-2) + shadow-mode rollout (jalankan kandidat paralel, log-only, sebelum switch).

### D-3. Quality gates + deteksi masker/sunglasses + temporal voting diperkuat (REC §0.2, 4.2, 2.3, 7, 9, 10.1)

- **Komponen**: INF (pipeline), FE-device/UI pintu (pesan "mendekatlah"/"lepas sunglasses").
- **Desain** (urutan per frame, sebelum liveness/embedding — gate murah dulu, kunci budget CPU):
  1. **C-1 Gate murah**: mean-luma ROI + variance-of-Laplacian (<1 ms) + ukuran wajah min (deteksi ≥64px, matching ≥80px, REC 10.1). Frame gagal gate = `skipped`, bukan reject — menunggu frame berikutnya dalam window voting. **Kriteria kelulusan log-only→enforcing (R-4/REV)**: gate boleh di-enforce bila estimasi frame sah ter-skip **< 1–2%** pada log D-1 selama **1–2 minggu, per device_class**; sebelum itu tetap log-only.
  2. **C-2 Deteksi masker + sunglasses (keputusan OQ-4/REV)**: **classifier 3-kelas tunggal milik sendiri** (`{masked, sunglasses, none}`, multi-label) — MobileNetV3-Small / ShuffleNetV2-0.5 / CNN 4-layer custom pada crop wajah 64×64–96×96, ONNX Runtime single-thread, ±1–3 ms CPU. Data training: frame enrollment sendiri + MaskTheFace sintetis + CelebA atribut `Eyeglasses` + augmentasi sunglasses sintetis + beberapa ratus foto lokal. **HINDARI detektor YOLOv5/v8 (GPL/AGPL)**. Heuristik landmark-confidence dan mean-intensity region mata = **sinyal sekunder/sanity-check saja**, bukan sinyal utama (landmark detector menebak fitur di bawah masker dengan confidence yang tidak reliably drop — NIST IR 8311). Output → `condition_flags`; dipakai D-2 (mode liveness), D-4 (mode threshold + prioritas template masked), dan UI ("lepaskan sunglasses" — REC 2.3: kebijakan, bukan pelonggaran τ).
  3. **C-3 FIQA ringan**: feature-norm AdaFace (gratis, hasil-samping embedding) sebagai gate terakhir sebelum vote (REC §7).
  4. **C-4 Voting existing diperkuat**: `min_frames_for_grant` sudah ada (`ai-inference/config.py:59-62`); tambah window eksplisit 3–5 frame + kebijakan "frame skipped tidak menghitung sebagai penolakan". 
  5. **C-5 [ABSENSI] Zona absensi + satu keputusan per approach (keputusan OQ-10/REV)**: proses wajah terbesar/terpusat di ROI; IoU tracker in-memory sederhana CUKUP di dalam satu batch (kontrak batch existing tidak berubah untuk voting). Untuk dedup lintas-request: **device menyertakan `capture_session_id`** (UUID per approach event, digenerate client saat wajah pertama masuk zona, reset saat zona kosong ≥2 dtk) — field opsional additive di `/recognize`; INF menyimpan cache TTL ≤10 dtk keyed `(device_id, capture_session_id)` untuk dedup keputusan + akumulasi voting lintas-batch. **TIDAK membangun tracker stateful server-side / streaming session.** Tie-break dua kandidat >τ selisih <0.05 → tolak & minta ulang (level keputusan, bukan tracker).
  6. **C-6 SCI enhancement low-light** (REC 1.3, MT; keputusan OQ-9/REV): checkpoint **`difficult.pt`** (repo vis-opt-group/SCI, dilatih DARK FACE — domain wajah malam), zero-shot dulu; fine-tune unsupervised pada frame malam lokal hanya bila muncul artefak yang menurunkan metrik end-to-end. Lisensi repo tidak jelas → risiko kecil untuk internal use (konsisten keputusan lisensi 2026-08-30); mitigasi murah tersedia: retraining self-supervised dari paper (<1 hari GPU kecil). Trigger: mean-luma ROI wajah **<50/255 dengan hysteresis** (aktif <50, nonaktif >70; final dikalibrasi dari histogram luma log D-1). +5–20 ms hanya pada frame gelap. **R-2 (WAJIB): frame hasil enhancement HANYA dikonsumsi stage deteksi (+alignment/embedding bila dipilih demikian — dan harus konsisten dengan kalibrasi); LIVENESS SELALU dievaluasi pada frame RAW** — enhancement menyuntik noise yang menipu model FAS (Wild-FAS: FAS rapuh terhadap shift input). Gate kelulusan C-6: evaluasi END-TO-END (Recall keputusan akhir, REC §0.4), bukan sekadar "deteksi naik".
- **Dependency**: C-1..C-3 independen; C-5 = perubahan kontrak `/recognize` additive (field opsional `capture_session_id`) + firmware/client device.
- **Impact**: latensi — worst case (malam+masker+voting) tetap <300 ms selama embedding hanya jalan pada frame lolos gate (anggaran REC §akhir). Regresi: gate terlalu ketat bisa MENURUNKAN Recall (frame sah dibuang) → semua ambang gate dikalibrasi dari log D-1, ship log-only dulu, enforce hanya setelah kriteria C-1 terpenuhi.

### D-4. Threshold multi-mode + template masked + matching (REC 4.4, 4.5, 12.2, 13)

- **Komponen**: BE (migrasi `face_embeddings`, tabel config, endpoint), TRN (A-4 generate template sintetis), INF (gallery query + decision).
- **Desain**:
  1. **Template masked sintetis**: A-4 (kolom `masked`, `template_kind='synthetic_masked'`). Probe ber-flag `masked` → prioritas match ke template `masked=true` (query pgvector dengan filter). **Fallback probe-masked tanpa template masked (keputusan OQ-3/REV)**: match ke template normal dengan **τ_masked** (mode longgar) + flag `low_confidence_masked` di access event; [AKSES] pertimbangkan minta lepas masker via UI pintu, [ABSENSI] terima + log. **Tidak ada τ ketiga** ("masked-vs-normal") — dua mode cukup. Fallback ini interim: dengan backfill D-4.5, populasi tanpa template masked menyusut ke nol (kecuali user yang videonya sudah lewat retensi — permanen sampai re-enroll).
  2. **τ dua-mode**: `τ_normal` / `τ_masked` per kurva FNIR@FPIR terpisah. **Sumber nilai (selaras keputusan OQ-6)**: default per-mode = properti hasil kalibrasi yang terikat `model_version` (metadata artefak/baris `models`); `recognition_configs` (key: `{scope, device_class, mode}` → delta `{similarity_threshold, margin, liveness_threshold, min_frames}`) = **override kebijakan**, diaudit (`audit_logs` existing). Konstanta env `INF_SIMILARITY_THRESHOLD` (`config.py:40`) tetap sebagai fallback terakhir.
  3. **Z-norm per-identitas** (REC 12.2, MT; keputusan OQ-5/REV): kolom `impostor_mean`/`impostor_std` per template, **disimpan berdampingan dengan `model_version`** (stats usang terdeteksi otomatis). Cohort impostor **frozen 200–500 template** dari gallery (atau embedding sintetis DCFace bila gallery kecil), sama untuk semua identitas, di-subsample seimbang per demografi. Hitung ulang: **penuh setiap `GALLERY_REEMBED`/ganti model** (digantung ke job itu); user baru = **incremental** vs cohort frozen; refresh cohort + hitung penuh bila gallery tumbuh **+25%**. Opsional fase 2 dari desain ini.
  4. **High-similarity pair** (REC 13): pada akhir embedding enrollment (TR-03) + pada re-embed, jalankan cek similarity template baru vs seluruh gallery; pasangan antar-identitas > (τ − margin_hs) → tulis tabel `identity_similarity_flags(user_a, user_b, score, flagged_at)` + naikkan τ per-identitas (kolom `threshold_override` di `users` atau di `recognition_configs` scope user) + kebijakan: [AKSES] wajib faktor kedua, [ABSENSI] konfirmasi UI + log foto.
  5. **D-4.5 — Job BACKFILL template masked untuk user legacy (R-1/REV, Gelombang 1)**: A-4 hanya berjalan pada enrollment BARU; tanpa backfill, mode masked pincang justru untuk populasi terbesar (user existing). Desain: **job satu-kali** (varian `GALLERY_REEMBED`; `training_jobs.job_type='BACKFILL_MASKED_TEMPLATES'`, B-1) — iterasi semua session ENROLLED (pola `run_gallery_reembed_job_core`, `ai-training/worker/tasks.py:532+`): baca video enrollment dari S3 → frame terbaik pose frontal + ±30° yaw → MaskTheFace (2 tipe masker, OQ-1) → insert 2–3 embedding `synthetic_masked`/user. Idempotent (skip user yang sudah punya), per-session failure isolation (pola existing). Prasyarat: media masih dalam retensi 90 hari (ASM-10); bila video sudah terhapus → fallback interim butir 1 berlaku permanen untuk user tsb sampai re-enroll (tandai `reenroll_due` via A-5).
- **Dependency**: A-4 & C-2 → (1); migrasi D-4.1 → (5); D-1 + benchmark D-7 → kalibrasi (2); (3) dan (4) independen setelah (2).
- **Impact**: keamanan — τ_masked lebih longgar menaikkan FPIR mode masked; mitigasi budget FPIR eksplisit per mode + template masked menurunkan FPIR pada Recall yang sama dibanding melonggarkan τ global (dukungan REV/NIST IR 8311 — **directional**, wajib validasi empiris D-7: eksperimen 3-konfigurasi {τ global longgar, τ_masked+template normal, τ_masked+template masked} pada FNIR@FPIR). Latensi +<2 ms (filter + Z-norm). Regresi: perubahan sumber threshold env→registry/DB adalah perubahan perilaku runtime INF → feature-flag + fallback env wajib. D-4.5: beban baca S3 satu-kali sebanding re-embed (menit untuk ≤5k user).

### D-5. Kalibrasi per-device-class (REC 10.3, 10.4)

- **Komponen**: BE (`devices` + `device_class`, `recognition_configs` scope device_class), TRN (kalibrasi), INF (resolve config by device).
- **Desain**: kolom `devices.device_class` (mis. `door_cam_a`, `webcam_enroll`, `absensi_panel`); INF sudah mengautentikasi device (`device_auth.py`) → decision path me-resolve `recognition_configs` by (device_class, mode). Kalibrasi = job evaluasi memakai probe dari `event_frames` per device_class (butuh D-1 `device_class` di events). **Soft re-enrollment hari pertama** (REC 10.4): accept skor tinggi dari kamera pintu → kandidat template `recent` via D-6.
- **Dependency**: D-1; D-4 (tabel config). 
- **Impact**: privasi — memakai event frames sebagai probe kalibrasi/template harus tercakup consent (cek teks consent existing; ASM-EC-05). Regresi rendah (additive; default class = konfigurasi global sekarang).

### D-6. Adaptive template update (REC 6.1) + kebijakan re-enrollment (REC 6.2)

- **Komponen**: BE (worker/beat), TRN (agregasi embedding), INF (tidak berubah — hanya membaca gallery).
- **Desain**: accept dengan liveness pass DAN skor ≥ τ+0.1 → simpan embedding probe ke buffer (tabel `template_candidates`); job mingguan mengagregasi per user → maks 2–3 template `template_kind='recent'` (rolling replace). **Guard anti-poisoning — 4 syarat WAJIB semuanya (R-3/OQ-7/REV; τ+0.1 saja tidak cukup)**:
  1. **Konsistensi temporal**: ≥3 accept pada ≥3 hari berbeda dalam window 14 hari sebelum cluster probe dipromosikan (menutup serangan satu-sesi).
  2. **Anchor ke identitas asli**: embedding kandidat wajib cosine ≥ τ terhadap template **`enrolled` asli** (bukan hanya terhadap `recent` sebelumnya) — mencegah drift berantai; drift sah (aging) bersifat gradual, lompatan besar = red flag.
  3. **Blokir user ber-flag `identity_similarity_flags`** (pasangan kembar/lookalike, D-4.4) — target poisoning paling realistis.
  4. **Hard liveness pass** — probe `liveness_soft_fail` (absensi) tidak pernah masuk buffer.
  Plus: template `enrolled` tidak pernah dihapus; kill-switch per user; audit setiap update. Re-enrollment due = A-5.
- **Dependency**: D-1 (log skor), migrasi D-4 (`template_kind`).
- **Impact**: **keamanan tertinggi kedua** — template poisoning berarti penyerang membangun akses permanen; mitigasi guard di atas + review berkala flag `identity_similarity_flags`. Privasi: embedding probe disimpan lebih lama dari event frame → perlu keputusan retensi (ASM-EC-06). Latensi 0 (offline job).

### D-7. Benchmark edge-case & audit bias (REC §0.4, 12.1, 3, 12.3)

- **Komponen**: TRN (benchmark set), QA (gate regresi), BE (metrik per-kelompok).
- **Desain**:
  1. **Slice**: masked-riil (bukan hanya sintetis — inilah gate penentu ASM-EC-04), masked-sintetis, low-light/dark, kacamata, hijab, blur, low-res, per demografi utama, **+ minimal 1 slice interaksi masked×demografi** (R-4/REV; temuan Mask-up: degradasi masker tidak merata antar demografi — cukup pelaporan dulu, belum gate). Lensa kosmetik 5–10 sampel = **smoke test berlabel demikian**, bukan gate (tidak signifikan statistik).
  2. **Komposisi statistik (keputusan OQ-8/REV — "rule of 30" NIST/ISO 19795)**: genuine per slice **≥30 identitas × ≥20 probe = ≥600 (ideal 1.000) keputusan**; impostor ≥10.000 perbandingan per slice (silang antar-identitas). Bila identitas internal terbatas (~30–50), kompensasi probe per identitas lebih banyak, TAPI laporkan **CI Wilson** dengan **bootstrap by-identity** (frame satu orang tidak independen).
  3. **Gate promosi**: **no-regression bertoleransi CI** — kandidat gagal bila Recall slice kritis turun melebihi lebar CI (atau >2 pp, mana yang lebih besar); bukan "harus lebih baik". Slice kritis minimum: masked-riil, dark, low-res, hijab, per-demografi utama.
  4. **Benchmark PAD beku (R-4/REV)**: test split PAD subject-disjoint (protokol OQ-2, lihat B-3) diformalkan sebagai benchmark beku milik D-7; **gate promosi model liveness = BPCER@APCER per mode** (budget: APCER ≤5% akses / ≤10% absensi) pada set ini.
  5. Evaluasi END-TO-END (deteksi→liveness→decision), bukan per-stage (REC §0.4) — hari ini `evaluate_candidate` menilai embedding matching; perlu mode e2e. Eksperimen 3-konfigurasi τ/template masked (D-4 impact) dijalankan di sini.
- **Dependency**: tidak ada untuk pembuatan set; gate baru menyusul B-1; set PAD menyusul koleksi data B-4.
- **Impact**: proses saja; tanpa risiko runtime.

### D-8. Panduan operasional kamera (REC 1.1, 1.2, 2.4, 5.2, 8.1, 9)

- **Komponen**: dokumen `documentation/operations/camera-placement-guide.md` (**lokasi final, keputusan 2026-09-01**: tidak di-commit, konsisten pola `planning/`/`research/` — bukan lampiran TSD) + checklist komisioning device di UI devices (field `commissioning_checklist jsonb`).
- **Isi**: kamera setinggi wajah 1.5–1.6 m (KRITIS absensi), fill-light, hindari backlight jendela, WDR/HDR + AE-lock wajah, shutter ≥1/250s, titik berhenti (bukan koridor), zona absensi digambar saat komisioning.
- **Dependency**: tidak ada. **Quick win terbesar per effort (REC prioritas #1) — bisa jalan sebelum semua kode.**

### D-9. Urutan dependency implementasi (untuk PM)

```
Gelombang 0 (tanpa kode / pondasi): D-8 (operasional) · D-1 (funnel logging) · D-7 (benchmark set)
Gelombang 1 (quick wins inference/enrollment): C-1..C-4 (gates+voting, log-only dulu; enforce per kriteria C-1)
                                               · C-2 (classifier mask/sunglasses 3-kelas)
                                               · A-2 (matched-condition text) · migrasi D-4.1 (kolom masked/template_kind/variant)
                                               · A-4 (template masked sintetis MaskTheFace)
                                               · B-1 (job_type/params — dimajukan: prasyarat D-4.5)
                                               · D-4.5 (BACKFILL template masked user legacy; setelah D-4.1+A-4+B-1)
                                               · D-4.2 (τ dua-mode: default terikat model + recognition_configs override)
                                               · D-4.4 (high-similarity check) · A-5 (re-enroll due)
Gelombang 2 (butuh data/training): B-4 (snapshot+PAD tooling ≥30 subjek, serangan AM2) → B-2 (finetune embedder)
                                   · B-3 (finetune liveness → threshold per-mode sbg metadata artefak)
                                   → D-2 (liveness per-mode) · D-5 (per-device-class)
Gelombang 3: D-6 (adaptive templates, 4 guard) · D-4.3 (Z-norm, cohort frozen 200–500)
             · A-1/A-3 (capture varian) · C-5 (capture_session_id) / C-6 (SCI difficult.pt, liveness tetap RAW) · B-5
Long-term backlog: RGB-IR, EUM/SRT, Retinexformer (out of scope desain)
```
(A-1 sengaja gelombang 3: nilai realnya baru terbukti setelah benchmark D-7 slice kacamata mengukur gap aktual — hemat perubahan UI bila augmentasi 2.2 sudah cukup.)

### D-10. Ringkasan perubahan skema DB (semua additive, alembic oleh BE)

| Tabel | Perubahan |
|---|---|
| `media_objects` | + `variant` (nullable enum-string) |
| `face_embeddings` | + `masked bool default false`; + `template_kind` (`enrolled|synthetic_masked|recent`); + (fase Z-norm) `impostor_mean`/`impostor_std` terikat `model_version` |
| `access_events` | + `condition_flags jsonb`; + `reject_stage`; + `device_class` (denormalized) |
| `devices` | + `device_class`; + `commissioning_checklist jsonb` |
| `training_jobs` | + `job_type` (incl. `BACKFILL_MASKED_TEMPLATES`); + `snapshot_id?`; + `params jsonb` |
| `models` | + `model_kind` (`embedder|liveness`) — DIPUTUSKAN (OQ-6/ASM-EC-07): satu tabel, kolom kind |
| Baru: `recognition_configs` | (scope: global/device_class/user, mode) → **delta/override** τ, margin, liveness_τ, min_frames di atas default artefak model; diaudit |
| Baru: `identity_similarity_flags` | pasangan high-similarity antar identitas |
| Baru: `template_candidates` | buffer embedding probe untuk adaptive update (retensi ketat) |

---

## 5. Daftar Asumsi (ASM-EC-xx)

| ID | Asumsi | Konsekuensi bila salah |
|---|---|---|
| ASM-EC-01 | Use case ABSENSI memakai pipeline & gallery yang SAMA dengan access control; perbedaan hanya kebijakan keputusan (τ, liveness_soft_fail, tie-break, zona) yang di-resolve per `device_class`. Tidak ada service absensi terpisah di fase ini. | Bila absensi jadi service terpisah, `recognition_configs` harus dipindah ke kontrak bersama |
| ASM-EC-02 | Untuk absensi, prioritas metrik tetap Recall→F1→Precision, TAPI mis-identifikasi (absen tercatat ke orang lain) diperlakukan setara-fatal dengan access-control false accept → tie-break reject (REC §11) diadopsi. | Kebijakan tie-break perlu ditinjau ulang |
| ASM-EC-03 | Varian kacamata cukup 1 foto frontal tambahan (bukan video 360° kedua); template varian non-frontal tidak sepadan dengan biaya UX-nya. | Bila gap Recall pose+kacamata besar di benchmark, A-1 diperluas jadi video pendek |
| ASM-EC-04 | Augmentasi masker sintetis (MaskTheFace, warp 2D landmark-based) dari frame enrollment cukup representatif untuk masker riil karyawan — sesuai klaim MFR Challenge 2021. **Dipertajam REV**: warp 2D tidak memodelkan bayangan/kontur 3D; asumsi ini baru dianggap TERBUKTI setelah lolos slice `masked-riil` di benchmark D-7 (gate penentu). | Fallback: langkah capture bermasker riil ditambahkan ke wizard |
| ASM-EC-05 | **(FINAL, keputusan user 2026-09-01)** Consent existing DIPERLUAS via mekanisme versioning existing (`consents.consent_version`, bump versi + record baru — bukan tabel/consent terpisah) untuk mencakup: template sintetis turunan, penggunaan event-frame kamera pintu sebagai template `recent`/probe kalibrasi, dan penyimpanan buffer embedding. Re-consent tidak memblokir user existing sampai re-enroll berikutnya. | Task implementasi: `task-breakdown.md` EC-BE-09/EC-FE-05 (prasyarat EC-TR-08/EC-TR-09) |
| ASM-EC-06 | **(FINAL, keputusan user 2026-09-01)** Retensi `template_candidates` (embedding probe) **≤ 90 hari** (disamakan ASM-10, retensi media enrollment); template `recent` mengikuti retensi embedding enrollment. | — (sudah final, tidak menunggu konsolidasi lebih lanjut) |
| ASM-EC-07 | **Disetujui REV**: registry `models` menampung model liveness lewat kolom `model_kind`; gate promosi liveness = **BPCER@APCER per mode pada test set PAD beku** (OQ-2/D-7.4), bukan Recall/F1 identifikasi. Default threshold per-mode disimpan sebagai metadata artefak model (OQ-6). | — (sudah dikonfirmasi riset) |
| ASM-EC-08 | Semua job training/fine-tune tetap human-triggered (konsisten FR-TRN-05); scheduler hanya evaluasi berkala + notifikasi. | — |
| ASM-EC-09 | **(Direvisi R-3/OQ-4)** Deteksi masker/sunglasses memakai **classifier 3-kelas milik sendiri** (MobileNetV3-Small-class, crop 64–96px, ONNX CPU) dalam anggaran 1–3 ms. Landmark-confidence/mean-intensity mata **hanya sinyal sekunder** — TIDAK boleh jadi satu-satunya sinyal (confidence landmark tidak reliably drop di bawah masker; NIST IR 8311). | Anggaran latensi D-3 direvisi |
| ASM-EC-10 | `liveness_soft_fail` (REC 14.3) HANYA aktif untuk `device_class` absensi, default OFF, dan setiap kejadian di-log + masuk antrean review. Pintu akses tidak pernah memakainya. | — |
| ASM-EC-11 | Lensa kontak bening/kosmetik: tanpa tindakan teknis (REC §3); 5–10 sampel probe di benchmark D-7 berstatus **smoke test** (bukan gate — tidak signifikan statistik, OQ-8). | — |
| ASM-EC-12 | **(Dipertajam OQ-2)** Data PAD lokal dikumpulkan operator internal dengan consent staf: **minimal 30 subjek bona fide subject-disjoint** (ideal 50–80), klip per spesifikasi B-3, **wajib menyertakan serangan bermasker tipe AM2** (masker riil pada print/replay — blind spot model pra-masker); disimpan prefix S3 `pad/`, retensi sama dengan media enrollment. | Jadwal B-3 mundur menunggu koleksi data |

---

## 6. Keputusan Desain — Resolusi OQ-1..OQ-10 (final, per review AI Researcher)

Semua open questions v0.1 telah dijawab di `documentation/research/papers/edge-cases/design-review-answers.md` dan keputusannya MENGIKAT untuk task breakdown. Ringkasan + lokasi integrasinya:

| OQ | Keputusan final | Terintegrasi di |
|---|---|---|
| OQ-1 | **MaskTheFace (MIT)**, dependensi dlib (Boost) — aman internal use. 2 tipe masker (surgical + kain gelap), full-coverage hidung; frame frontal + ±30° yaw → 2–3 template `synthetic_masked`/user. Validasi akhir = slice masked-riil D-7. | A-4, D-4.5, ASM-EC-04 |
| OQ-2 | Dataset PAD: **≥30 subjek bona fide subject-disjoint** (ideal 50–80), 4 klip/subjek ({normal, dark}×{masker on, off}), ≥3 print + ≥3 replay device, **serangan AM2 wajib**; split 60/20/20 by-subject; kalibrasi di val (budget APCER ≤5% akses / ≤10% absensi), lapor BPCER@APCER di test; test split = benchmark PAD beku. | B-3, D-2, D-7.4, ASM-EC-12 |
| OQ-3 | Klaim Precision template masked didukung directionally (NIST IR 8311) — validasi via eksperimen 3-konfigurasi di D-7. Fallback probe-masked tanpa template masked: match template normal dengan τ_masked + flag `low_confidence_masked`; **tidak ada τ ketiga**. Gap legacy ditutup backfill D-4.5. | D-4.1, D-4.5, D-7.5 |
| OQ-4 | **Classifier 3-kelas milik sendiri** ({masked, sunglasses, none}, MobileNetV3-Small-class, crop 64–96px, ONNX, 1–3 ms CPU); hindari YOLO (GPL/AGPL); landmark-confidence = sinyal sekunder saja. | C-2, ASM-EC-09 |
| OQ-5 | Cohort impostor **frozen 200–500 template**, seimbang per demografi; hitung penuh setiap re-embed/ganti model (digantung ke `GALLERY_REEMBED`), incremental untuk user baru, refresh cohort saat gallery +25%; stats disimpan terikat `model_version`. | D-4.3 |
| OQ-6 | **Default threshold per-mode = metadata artefak model di MLflow** (rollback atomik); `recognition_configs` = override/delta kebijakan (device_class, budget absensi vs akses, kill-switch). Berlaku juga untuk τ matching bila embedder di-fine-tune. | D-2.3, D-4.2, B-3, D-10 |
| OQ-7 | τ+0.1 wajar tapi tidak cukup sendiri → **4 guard**: (1) ≥3 accept di ≥3 hari berbeda /14 hari, (2) cosine ≥ τ vs template `enrolled` asli, (3) blokir user high-similarity pair, (4) hard liveness pass. | D-6 |
| OQ-8 | **Rule-of-30**: ≥30 identitas × ≥20 probe (≥600, ideal 1.000 genuine) + ≥10.000 impostor per slice; CI Wilson + bootstrap by-identity bila identitas terbatas; gate = **no-regression bertoleransi CI** (turun > max(lebar CI, 2 pp) = gagal); lensa kosmetik = smoke test. | D-7.2/7.3, ASM-EC-11 |
| OQ-9 | SCI checkpoint **`difficult.pt`** (DARK FACE), zero-shot dulu; trigger luma <50/255 dengan hysteresis (<50 on, >70 off); lisensi repo tidak jelas → acceptable internal + mitigasi retraining self-supervised <1 hari; **liveness tetap pada frame RAW (R-2)**; gate kelulusan end-to-end. | C-6, D-2.5 |
| OQ-10 | Batch existing cukup untuk voting; dedup lintas-request via **`capture_session_id` client-generated** (field opsional additive di `/recognize`) + cache INF TTL ≤10 dtk; tidak ada tracker stateful server-side. | C-5 |

**Status review**: tidak ada pertentangan fatal dengan literatur (REV Bagian 2a); 4 revisi yang diminta (R-1 backfill, R-2 liveness-on-raw, R-3 guard×4 + demosi landmark-only, R-4 slice interaksi/kriteria gate/PAD beku) sudah terintegrasi di v0.2. **Dokumen siap diserahkan ke Project Manager untuk task breakdown** (peta komponen per item: FE/BE/TRN/INF tercantum di tiap D-x; urutan dependency di D-9; migrasi DB di D-10).
