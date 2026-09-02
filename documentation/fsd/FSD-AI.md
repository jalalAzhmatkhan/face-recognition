# FSD-AI — Face Recognition Access Control

> Functional Specification Document (machine-readable edition).
> Audience: AI agents (ai-researcher, uiux-designer, project-manager, ai-engineer, backend-engineer, frontend-engineer, qa-engineer).
> Status: DRAFT v0.1 — planning phase. No implementation exists yet.
> Companion docs: `documentation/fsd/FSD-USER.md` (layman, ID), `documentation/tsd/TSD.md` (technical spec).

---

## 1. System Overview

- **SYS-01**: The system authorizes physical entry to a building/office using face recognition.
- **SYS-02**: Monorepo modules: `frontend/`, `backend/`, `ai-inference/`, `ai-training/`, `qa/`.
- **SYS-03**: Core loop: **Enroll** (capture frontal photo + one photo burst per clock position across the 360° head-orientation sweep) → **Store media in AWS S3** → **Train/fine-tune model + build embedding gallery** → **Deploy model** → **Real-time inference at entry point** → **Grant/deny access + audit log**.
- **SYS-04**: Capture-quality and head-pose-detection thresholds are **runtime configuration, not constants** — ADMIN retunes them from the System Parameter menu without a redeploy (`system_parameters.enrollment_capture_quality`). One row backs both halves of the gate: the browser's live preflight (sharpness, brightness, per-axis pose gain, pose radius) and ai-training's server-side QC (`pose_tolerance_deg`). They are kept together deliberately, because loosening one side alone converts a "position never lights up" complaint into a `REJECTED_QUALITY: pose_out_of_range` one. Every value ships as an uncalibrated starting point.

## 2. Actors

| ID | Actor | Description |
|---|---|---|
| ACT-01 | Admin | Manages users, enrollments, devices, access policies; views audit logs. |
| ACT-02 | Operator/Security | Monitors live access events; handles manual override. |
| ACT-03 | Enrollee | Person being enrolled; consents to biometric capture. |
| ACT-04 | Entry Device | Camera + door controller at entry point; consumes inference service. |
| ACT-05 | ML Engineer | Triggers/reviews training runs and model promotion. |
| ACT-06 | System (scheduler) | Automated retraining, retention cleanup, monitoring. |

## 3. Functional Requirements

### 3.1 Enrollment (FR-ENR)

- **FR-ENR-01**: Admin creates an enrollment session for a user (new or re-enrollment).
- **FR-ENR-02**: Frontend captures: (a) ≥1 frontal still photo, which also serves as the **neutral-pose reference** for QC (see FR-ENR-06); (b) a set of **still photos, one short burst (3–5 frames) per clock position**, captured automatically the moment the subject's live head orientation is detected at that position. The subject sweeps **head orientation** from 12 o'clock **clockwise** back to 12 o'clock (body stays facing the camera; only head yaw/pitch changes — see ASM-03, corrected 2026-08-30). ≥720p. Positions may be covered in any order and re-shot individually; a burst is kept so the embedding extractor still has multiple frames to average and pick sharpness from. *(Superseded 2026-09-02: previously one 10–20 s `video/webm` of the whole sweep. Sessions enrolled before this change keep their video, and both the backend contract and the ai-training pipeline continue to accept it — see TSD.md §7.)*
- **FR-ENR-03**: Frontend MUST provide real-time guidance during capture: face-in-frame check, head-orientation progress indicator (clock positions covered), lighting/blur warnings, and retry flow. The browser-side pose estimator is a landmark-ratio approximation whose sensitivity differs sharply between axes (it under-reports pitch by roughly 3x relative to yaw), so its per-axis **gain and radius threshold MUST be operator-tunable** rather than hardcoded — otherwise the pitch-dominant clock positions (11, 12, 1 and 5, 6, 7) are unreachable in practice. See SYS-04.
- **FR-ENR-04**: All captured media MUST be uploaded directly to AWS S3 via backend-issued presigned URLs. Media MUST NOT be persisted on client disk or on any server local disk; only transient in-memory/temp buffers that are deleted immediately are allowed (non-negotiable rule; see NFR-SEC-02).
- **FR-ENR-05**: Backend validates completed uploads (object exists, size/type/duration bounds, checksum) before marking the session `CAPTURED`. A session MUST carry the frontal photo plus **exactly one** sweep shape — per-position photos or one legacy video, never both and never neither.
- **FR-ENR-06**: A quality-check job (async) validates captured media: face detected in stills; sufficient head-pose coverage across (yaw, pitch) combinations mapped from clock positions (no back-of-head segment exists — see ASM-03); sharpness/exposure thresholds. Each sweep frame's measured pose is checked against **the clock position it was captured for**, and against a **per-subject neutral baseline** estimated from the frontal photo — without that baseline, a subject whose resting head pose is not perfectly level fails the lower half of the dial (positions 4–8) even when they are looking exactly where they were asked to. For legacy video sessions, coverage is derived from sampled frames instead. On failure the session becomes `REJECTED_QUALITY` with machine-readable reasons; the frontend prompts re-capture (per position, where available).
- **FR-ENR-07**: On quality pass, an embedding-extraction job produces multi-view face embeddings (frames sampled across the rotation) and stores them in the vector store, linked to the user (`identity gallery`). Session becomes `ENROLLED`.
- **FR-ENR-08**: Enrollment requires recorded **consent** (who, when, consent text version) before capture can start.
- **FR-ENR-09**: Admin can revoke/delete an enrollment: gallery embeddings are deleted, S3 media deleted (or lifecycle-expired per retention policy), and the user can no longer be recognized.

### 3.2 Training (FR-TRN)

- **FR-TRN-01**: `ai-training/` pipeline: ingest media from S3 → frame extraction/sampling → preprocessing (detection, alignment, augmentation) → EDA/quality reports → fine-tuning of the face-embedding model → evaluation → model registration.
- **FR-TRN-02**: Training jobs can be triggered (a) manually by ML Engineer/Admin, (b) automatically when N new enrollments accumulate or on schedule (thresholds configurable).
- **FR-TRN-03**: Every run MUST be logged in the experiment tracker: dataset snapshot/version, hyperparameters, metrics, artifacts.
- **FR-TRN-04**: Evaluation metrics, in priority order: **Recall (primary)** → **F1** → **Precision**, computed on a held-out identification/verification benchmark; plus **inference latency (ms)** measured on the target inference hardware.
- **FR-TRN-05**: Model promotion gate: a candidate model is promoted to `production` only if Recall ≥ current production Recall (no regression) AND latency budget respected (see NFR-PRF-01). Promotion is an explicit approval step (human-in-the-loop) in v1.
- **FR-TRN-06**: After model promotion, gallery embeddings MUST be re-extracted with the new model version (embedding-space consistency); rollout is atomic per model version (no mixed-version matching).

### 3.3 Inference / Access Control (FR-INF)

- **FR-INF-01**: `ai-inference/` exposes a low-latency recognition API: input = frame(s) from the entry camera; pipeline = face detection → alignment → liveness/anti-spoofing check → embedding → vector similarity search against gallery → threshold decision.
- **FR-INF-02**: Output: `{decision: GRANTED|DENIED|UNKNOWN, user_id?, similarity_score, liveness_score, latency_ms, model_version}`.
- **FR-INF-03**: Decision threshold is configurable and tuned to prioritize Recall for enrolled users while keeping false-accepts bounded (see ASM-07 on FAR bound).
- **FR-INF-04**: Every attempt (granted, denied, unknown, spoof-suspected) is recorded as an **access event** with timestamp, device, decision, score, model version. Event capture frames follow the same S3-only rule (FR-ENR-04) if retained.
- **FR-INF-05**: On `GRANTED`, backend commands the door controller (or returns a signed decision the device enforces). Fail-secure default: on inference-service outage the door does NOT auto-open; manual/operator fallback applies.
- **FR-INF-06**: Liveness/anti-spoof check MUST reject photo/screen replays at the entry point (v1: passive, frame-based; hardware-assisted depth/IR is out of scope v1 — ASM-08).

### 3.4 User & Access Management (FR-USR)

- **FR-USR-01**: CRUD users (employee/visitor), with status (`ACTIVE`, `SUSPENDED`, `OFFBOARDED`). Non-active users are never granted access even on a face match.
- **FR-USR-02**: Role-based access for the web app: `ADMIN`, `OPERATOR`, `VIEWER` (staff auth for the console is separate from face-based door authorization).
- **FR-USR-03**: Access policies: per-user or per-group validity (schedules/doors) — v1 minimal: allowed/not-allowed per door group.
- **FR-USR-04**: Device registry: entry devices are registered, authenticated (per-device credential/mTLS token), and monitorable (online/offline heartbeat).

### 3.5 Monitoring & Audit (FR-MON)

- **FR-MON-01**: Live access-event feed in the frontend (websocket/SSE) for operators.
- **FR-MON-02**: Dashboards: daily grants/denies, unknown rate, average latency, model version in production, enrollment funnel.
- **FR-MON-03**: Immutable audit log for admin actions (enroll, revoke, threshold change, model promotion, data deletion).
- **FR-MON-04**: Model monitoring: score-distribution drift, unknown-rate spikes, latency SLO breaches → alerts.

## 4. Non-Functional Requirements

### Performance (NFR-PRF)
- **NFR-PRF-01**: End-to-end recognition decision (frame received by inference service → decision) p95 **≤ 300 ms**; full door experience (capture → door signal) p95 ≤ 1 s. Latency reported in **ms** per request.
- **NFR-PRF-02**: Vector search over the gallery ≤ 10 ms p95 at v1 scale (≤ 5,000 identities — ASM-05).
- **NFR-PRF-03**: Enrollment upload path must sustain the full capture set without routing bytes through backend memory (presigned direct-to-S3): up to ~60 still frames of a few hundred KB each, uploaded progressively as each clock position is captured, and — for legacy sessions — single video files of 50–200 MB. Because upload is progressive, an early position's presigned URL may well have expired by the time the session is completed; completion therefore keys off whether the object actually landed in S3, not off the URL's age.

### Security & Privacy (NFR-SEC)
- **NFR-SEC-01**: Biometric data (media + embeddings) is sensitive personal data (Indonesia UU PDP No. 27/2022 classifies biometric data as sensitive). Consent, purpose limitation, retention, and deletion rights MUST be implemented.
- **NFR-SEC-02**: Media at rest ONLY in S3, encrypted (SSE-KMS), bucket private, access via short-lived presigned URLs; TLS everywhere in transit. No media on local disks (non-negotiable).
- **NFR-SEC-03**: Embeddings stored encrypted at rest; deletion of a user cascades to embeddings, media, and (via lifecycle) backups per retention policy.
- **NFR-SEC-04**: AuthN/AuthZ: staff console via OIDC/JWT + RBAC; devices via per-device credentials; all APIs deny-by-default.
- **NFR-SEC-05**: Audit logging (FR-MON-03) is append-only and access-restricted.
- **NFR-SEC-06**: Anti-spoofing (FR-INF-06) is a security control, not just a quality feature; spoof-suspected events raise operator alerts.

### Reliability & Operations (NFR-OPS)
- **NFR-OPS-01**: Inference availability target 99.5% during building hours; fail-secure on outage (FR-INF-05).
- **NFR-OPS-02**: Training and enrollment-processing are async and retryable (idempotent jobs, dead-letter handling).
- **NFR-OPS-03**: All services containerized; config via environment; secrets never in repo.
- **NFR-OPS-04**: Structured logs + metrics + traces from all services.

### Quality (NFR-QA)
- **NFR-QA-01**: QA (`qa/`, Python + Playwright via `uv`) covers: enrollment E2E (mock camera streams), API contract tests, recognition regression suite against a fixed benchmark set, and the promotion-gate metrics check. QA must PASS before any PR (per repo workflow).

## 5. Explicit Assumptions (need user confirmation)

| ID | Assumption |
|---|---|
| ASM-01 | Enrollment is **supervised**, performed on-site by an Admin/Operator using the web app on a device with a camera (not self-service remote enrollment). |
| ASM-02 | Entry device = camera + controllable door lock; integration contract with the physical lock is abstracted as a "door controller API" (exact hardware TBD). |
| ASM-03 | **CORRECTED 2026-08-30 (user clarification, supersedes original text):** "360° rotation clockwise from 12 back to 12" refers to **head orientation only** (yaw + pitch), not the body or camera rotating. The subject's body stays facing the camera throughout; the head sweeps through a clock-face pattern of pose combinations — e.g. 12 o'clock = head tilted up (mendongak/pitch), then clockwise through combinations of yaw (looking left/right) and pitch (up/down), back to 12. The face remains visible to the camera at all times — **there is no back-of-head segment to sample out**. QC and pose-bin sampling (TR-02/TR-03) must map each clock position to a (yaw, pitch) pair within a realistic head-pose range, not to a full-profile/rear-view rotation. This also means the achievable pose-bin coverage for the embedding gallery is narrower than a full 360° head turn — AI Researcher/AI Engineer should re-derive the practical yaw/pitch range and pose-bin count for TR-02/TR-03 against this corrected motion, and Frontend/UI-UX should update capture guidance (FE-04, `documentation/uiux/`) accordingly before those tasks are implemented. |
| ASM-04 | Recognition mode is **identification (1:N)** against the enrolled gallery, not 1:1 verification with a claimed identity. |
| ASM-05 | v1 scale: ≤ 5,000 enrolled identities, ≤ 20 entry devices, single site/region. |
| ASM-06 | Base model strategy: pretrained SOTA face-embedding backbone (ArcFace-family) fine-tuned on enrollment data; final choice deferred to AI Researcher output (`documentation/research/`). |
| ASM-07 | Recall priority is bounded: target Recall ≥ 0.98 for enrolled users while FAR (false accept of non-enrolled) ≤ 0.1%; thresholds tuned on validation data. |
| ASM-08 | v1 anti-spoofing is software/passive only (RGB frames); depth/IR hardware liveness is a later phase. |
| ASM-09 | GPU is available for training; inference target hardware is a server GPU or capable CPU near the edge — Rust/ONNX path is an optimization option, not required for MVP. |
| ASM-10 | Retention default: raw enrollment media retained 90 days after successful embedding extraction then lifecycle-deleted; embeddings retained while user is active. Configurable. |
| ASM-11 | Frontend stack (proposed, to be ratified with Frontend Engineer): React + TypeScript + Vite, since MediaRecorder/WebRTC-based capture and a mature ecosystem are needed. |
| ASM-12 | Offboarded/lost-consent users are removed from the gallery within 24 h (async cleanup SLA). |

## 6. Out of Scope (v1)

- Mobile native apps; badge/PIN fallback hardware integration beyond a generic controller API; multi-site federation; on-device (edge) model deployment; video surveillance/retention beyond access events; emotion/attribute analysis (explicitly excluded — privacy).

## 7. High-Level API Surface (contract detail in TSD §7)

| Domain | Endpoints (backend unless noted) |
|---|---|
| Auth | `POST /auth/login`, `POST /auth/refresh` |
| Users | `GET/POST /users`, `GET/PATCH/DELETE /users/{id}` |
| Enrollment | `POST /enrollments`, `POST /enrollments/{id}/consent`, `POST /enrollments/{id}/media/presign`, `POST /enrollments/{id}/complete`, `GET /enrollments/{id}` (status incl. quality result), `DELETE /enrollments/{id}` |
| Training | `POST /training/jobs`, `GET /training/jobs/{id}`, `POST /models/{version}/promote`, `GET /models` |
| Recognition | `POST /recognize` (ai-inference, device-authenticated), `GET /healthz`, `GET /metrics` |
| Events | `GET /access-events` (filterable), `GET /stream/access-events` (SSE/WS) |
| Devices | `GET/POST /devices`, `POST /devices/{id}/heartbeat` |

## 8. State Machines

### Enrollment session
`CREATED → CONSENTED → CAPTURING → CAPTURED → QC_RUNNING → (REJECTED_QUALITY → CAPTURING) | QC_PASSED → EMBEDDING → ENROLLED`
Terminal alternates: `CANCELLED`, `REVOKED`.

### Model version
`TRAINING → TRAINED → EVALUATED → (REJECTED | CANDIDATE) → PROMOTED(production) → RETIRED`

## 9. Traceability

- Non-negotiable repo rules mapped: S3-only media → FR-ENR-04/NFR-SEC-02; metric order → FR-TRN-04; 360° enrollment → FR-ENR-02/03/06.
- Technical realization of every FR/NFR: see `documentation/tsd/TSD.md`.
