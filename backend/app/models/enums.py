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
