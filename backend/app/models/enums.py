"""Python-side enums mirrored by Postgres native ENUM types.

Kept as plain `str` enums so Pydantic schemas (later tasks) and SQLAlchemy
`Enum(..., native_enum=True)` columns can share the same source of truth.
"""

import enum


class UserStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    OFFBOARDED = "OFFBOARDED"


class StaffRole(enum.StrEnum):
    ADMIN = "ADMIN"
    OPERATOR = "OPERATOR"
    VIEWER = "VIEWER"


class EnrollmentState(enum.StrEnum):
    """State machine per FSD-AI.md §8:

    CREATED -> CONSENTED -> CAPTURING -> CAPTURED -> QC_RUNNING ->
        (REJECTED_QUALITY -> CAPTURING) | QC_PASSED -> EMBEDDING -> ENROLLED
    Terminal alternates: CANCELLED, REVOKED.
    """

    CREATED = "CREATED"
    CONSENTED = "CONSENTED"
    CAPTURING = "CAPTURING"
    CAPTURED = "CAPTURED"
    QC_RUNNING = "QC_RUNNING"
    REJECTED_QUALITY = "REJECTED_QUALITY"
    QC_PASSED = "QC_PASSED"
    EMBEDDING = "EMBEDDING"
    ENROLLED = "ENROLLED"
    CANCELLED = "CANCELLED"
    REVOKED = "REVOKED"


class MediaKind(enum.StrEnum):
    PHOTO = "photo"
    VIDEO = "video"
    EVENT_FRAME = "event_frame"


class MediaObjectStatus(enum.StrEnum):
    """Lifecycle of a `media_objects` row across the presign/complete flow
    (BE-06, FR-ENR-04/05).

    A row is created as `PENDING` the moment a presigned upload URL is
    issued (it records what the client *claims* it will upload — kind,
    content-type, size, checksum — before any bytes exist in S3). It only
    becomes `FINALIZED` once `POST /enrollments/{id}/complete` confirms via
    S3 HEAD that the object actually exists and the claimed metadata is
    truthful (see app/services/media_service.py). A `PENDING` row with no
    matching S3 object is exactly what `/complete` treats as "media
    missing" (422) — it never transitions the session's state.
    """

    PENDING = "PENDING"
    FINALIZED = "FINALIZED"


class ModelStage(enum.StrEnum):
    CANDIDATE = "CANDIDATE"
    PRODUCTION = "PRODUCTION"
    RETIRED = "RETIRED"


class ModelKind(enum.StrEnum):
    """What a `models` row actually is (EC-BE-06, TSD-edge-cases.md B-3).

    Every row before this column existed is an `EMBEDDER` (the only kind
    that ever existed — `models` backfills to it, see migration
    `c8f3a2e6d9b1`). `LIVENESS` is EC-TR-07's `FINETUNE_LIVENESS`
    output: a MiniFASNet-family PAD model, evaluated on a completely
    different metric (BPCER@APCER per mode, not Recall/F1/precision) and
    promoted independently — each kind has its OWN PRODUCTION slot, so an
    embedder and a liveness model can both be `stage=PRODUCTION`
    simultaneously without either affecting the other's promotion gate
    (`app/services/training_service.py::promote_model` scopes its
    current-production lookup and its retire-on-promote step by the
    candidate's own kind, never globally across kinds).
    """

    EMBEDDER = "embedder"
    LIVENESS = "liveness"


class TrainingJobStatus(enum.StrEnum):
    """Lifecycle of a `training_jobs` row (BE-13, FR-TRN-02).

    PENDING is set at creation time (before the Celery dispatch is even
    attempted); RUNNING is set by the ai-training worker right after it
    picks the job up; SUCCEEDED/FAILED are terminal. There is no CANCELLED
    state in v1 — cancelling an in-flight evaluation job is out of scope.
    """

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class TrainingJobType(enum.StrEnum):
    """Kind of `training_jobs` row (EC-BE-03, TSD-edge-cases.md B-1/D-10).

    `EVALUATION` is the only kind that existed before this column — every
    pre-EC-BE-03 row backfills to it (see the EC-BE-03 migration), and its
    validation/dispatch behaviour is UNCHANGED (still requires
    `model_version` + `benchmark_id`, still dispatches
    `run_training_evaluation_job`). The other four kinds formalize job
    types that either had no API surface at all (`GALLERY_REEMBED` — TR-08
    already runs this as a side effect of promotion, this just lets it be
    triggered/tracked as a first-class job) or do not exist yet
    (`FINETUNE_EMBEDDER`/B-2, `FINETUNE_LIVENESS`/B-3,
    `BACKFILL_MASKED_TEMPLATES`/D-4.5) — this task (B-1) only added the
    schema + request validation for them. `BACKFILL_MASKED_TEMPLATES`'s
    Celery task and dispatch have since landed (EC-TR-03/D-4.5, see
    `ai_training/worker/tasks.py::run_backfill_masked_templates_job` +
    `app/services/training_queue.py::enqueue_backfill_masked_templates_job`);
    `FINETUNE_EMBEDDER`/`FINETUNE_LIVENESS` remain separate, later tasks —
    creating a job of either of those two types today still persists a
    validated row without dispatching anything.
    """

    EVALUATION = "EVALUATION"
    FINETUNE_EMBEDDER = "FINETUNE_EMBEDDER"
    FINETUNE_LIVENESS = "FINETUNE_LIVENESS"
    GALLERY_REEMBED = "GALLERY_REEMBED"
    BACKFILL_MASKED_TEMPLATES = "BACKFILL_MASKED_TEMPLATES"


class DeviceStatus(enum.StrEnum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    DISABLED = "DISABLED"


class DeviceClass(enum.StrEnum):
    """Denormalized device category (EC-BE-01, TSD-edge-cases.md D-5/D-10).

    Drives per-device-class recognition-policy resolution (threshold/mode
    overrides in `recognition_configs`, a later task) and the operational
    commissioning checklist (D-8). `UNKNOWN` is the safe default for
    devices registered before this column existed, or where the operator
    hasn't classified the device yet — it must never be treated as an
    error state.
    """

    DOOR_ENTRY = "door_entry"
    ATTENDANCE = "attendance"
    UNKNOWN = "unknown"


class RejectStage(enum.StrEnum):
    """Which pipeline stage produced a non-GRANTED `/recognize` decision
    (EC-BE-01, TSD-edge-cases.md D-1). Populated by ai-inference on
    `access_events.reject_stage` — NULL means "not a reject" (e.g.
    decision=GRANTED) or "reported by a caller that predates this field".

    Values per D-1 / EC-IN-01: `detection` (no face found), `liveness`
    (spoof/PAD failure), `quality_gate` (frame gates C-1..C-3 — blur/dark/
    low-res/masked-without-fallback), `threshold` (matched below
    similarity threshold for the resolved mode), `policy` (matched +
    passed threshold, but door policy/access-control denied it — mirrors
    the existing `door_command_issued=False` fail-secure paths).
    """

    DETECTION = "detection"
    LIVENESS = "liveness"
    QUALITY_GATE = "quality_gate"
    THRESHOLD = "threshold"
    POLICY = "policy"


class MediaVariant(enum.StrEnum):
    """Capture variant of a `media_objects` row (EC-BE-02, TSD-edge-cases.md
    D-4.1/D-10 — A-1/A-3 capture-variant design).

    `DEFAULT` is the ordinary 360 head-orientation-sweep capture (FR-ENR-03).
    The other three are optional extra captures a later frontend task
    (gelombang 3, A-1/A-3) may request to improve matching under glasses/
    lighting/pitch edge cases: `NO_GLASSES`/`GLASSES` (capture with/without
    eyewear removed) and `PITCH_EXT` (extended up/down pitch sweep beyond the
    baseline 360 yaw rotation). Nullable at the DB level (pre-EC-BE-02 rows
    have no variant on record), but `POST .../media/presign` always writes
    `DEFAULT` when the caller omits `variant` — see
    app/services/media_service.py::request_presign.
    """

    DEFAULT = "default"
    NO_GLASSES = "no_glasses"
    GLASSES = "glasses"
    PITCH_EXT = "pitch_ext"


class TemplateKind(enum.StrEnum):
    """Provenance of a `face_embeddings` row (EC-BE-02, TSD-edge-cases.md
    D-4.1/D-10).

    `ENROLLED` = produced by the ordinary enrollment embedding pipeline
    (TR-03) — the only kind that has ever existed before this column, so
    every pre-EC-BE-02 row backfills to this value (see the EC-BE-02
    migration). `SYNTHETIC_MASKED` = MaskTheFace-augmented template
    generated by the A-4/D-4.5 masked-template pipeline (a later task).
    `RECENT` = adaptive rolling template captured from live accept events
    (D-6, a later task; NOT the same thing as a `RejectStage`/access-event
    concept despite the similar name).
    """

    ENROLLED = "enrolled"
    SYNTHETIC_MASKED = "synthetic_masked"
    RECENT = "recent"


class AccessDecision(enum.StrEnum):
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    SPOOF_SUSPECTED = "SPOOF_SUSPECTED"
    # BE-10 (FR-INF-02): distinct from SPOOF_SUSPECTED — "no liveness/spoof
    # concern, but the face didn't match anyone (or not confidently enough)".
    # Added via an additive `ALTER TYPE ... ADD VALUE` migration (see
    # migrations/versions/ for the BE-10 enum migration) rather than the
    # baseline schema migration, since this value didn't exist until BE-10.
    UNKNOWN = "UNKNOWN"


class RecognitionConfigScope(enum.StrEnum):
    """Scope a `recognition_configs` override row applies to (EC-BE-04,
    TSD-edge-cases.md D-4.2/D-10, OQ-6).

    Resolution priority when several scopes could apply to the same
    `(mode)` lookup is `USER` (most specific) > `DEVICE_CLASS` >
    `GLOBAL` (least specific) — see
    `app/services/recognition_config_service.py::resolve_recognition_config`,
    the contract later consumed by EC-IN-04 (ai-inference)/EC-TR-08
    (ai-training). `scope_ref` on the row holds the value this scope keys
    on: NULL for `GLOBAL`, a `devices.device_class` value (e.g. `door_entry`)
    for `DEVICE_CLASS`, a `users.id` (stringified UUID) for `USER`.
    """

    GLOBAL = "global"
    DEVICE_CLASS = "device_class"
    USER = "user"
