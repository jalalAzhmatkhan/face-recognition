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


class DeviceStatus(enum.StrEnum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    DISABLED = "DISABLED"


class AccessDecision(enum.StrEnum):
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    SPOOF_SUSPECTED = "SPOOF_SUSPECTED"
