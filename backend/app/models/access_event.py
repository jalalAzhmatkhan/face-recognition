"""access_events — inference decisions, PARTITIONED BY MONTH on occurred_at (TSD §4).

Native Postgres declarative range partitioning requires the partition key
(`occurred_at`) to be part of every unique constraint, including the primary
key — hence the composite PK `(id, occurred_at)` instead of a bare `id`.
Partitions themselves (monthly children) are created in the alembic migration,
not here; SQLAlchemy only needs to know about the parent table's shape.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import AccessDecision, DeviceClass, RejectStage


class AccessEvent(Base):
    __tablename__ = "access_events"
    __table_args__ = (
        PrimaryKeyConstraint("id", "occurred_at"),
        {"postgresql_partition_by": "RANGE (occurred_at)"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("devices.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    decision: Mapped[AccessDecision] = mapped_column(
        Enum(AccessDecision, name="access_decision", native_enum=True), nullable=False
    )
    matched_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    similarity: Mapped[float | None] = mapped_column(Float)
    liveness_score: Mapped[float | None] = mapped_column(Float)
    model_version: Mapped[str | None] = mapped_column(
        ForeignKey("models.version", ondelete="SET NULL")
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    frame_media_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_objects.id", ondelete="SET NULL")
    )
    # BE-10 (FR-INF-05): the EFFECTIVE door decision after policy evaluation —
    # distinct from `decision`, which is the raw inference result. A row can
    # have decision=GRANTED yet door_command_issued=False (fail-secure: cache
    # miss, SUSPENDED/OFFBOARDED user, no matching door_group policy, outside
    # valid_from/valid_to window). See app/services/access_event_service.py.
    door_command_issued: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # EC-BE-01 (TSD-edge-cases.md D-1 — funnel logging, PONDASI for the rest
    # of the edge-case design). Populated by ai-inference's `/recognize`
    # decision via `POST /access-events`; all three columns are nullable so
    # callers that predate this field (or a decision that doesn't apply,
    # e.g. GRANTED has no reject_stage) stay valid.
    #
    # `condition_flags`: per-frame condition signals at decision time — the
    # canonical keys are `masked`, `dark`, `blurry`, `low_res`,
    # `sunglasses` (booleans), but this is intentionally NOT a DB-level
    # shape constraint (see app/schemas/access_events.py) so INF can add a
    # new flag without a migration.
    condition_flags: Mapped[dict | None] = mapped_column(JSONB)
    # Which pipeline stage produced a non-GRANTED decision (see
    # app/models/enums.py::RejectStage). NULL = GRANTED, or reported by a
    # pre-EC-BE-01 caller.
    reject_stage: Mapped[RejectStage | None] = mapped_column(
        Enum(
            RejectStage,
            name="reject_stage",
            native_enum=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        )
    )
    # Denormalized copy of `devices.device_class` AT THE TIME OF THE EVENT
    # (set server-side from the authenticated device row in
    # app/services/access_event_service.py — never trusted from the
    # request body), so funnel-logging/monitoring queries can group by
    # device class without joining `devices` (and so the historical value
    # survives a later device reclassification). Nullable rather than
    # defaulting to `unknown` here: unlike `devices.device_class` (always
    # knowable at write time), a NULL here also legitimately means "this
    # row predates the column".
    device_class: Mapped[DeviceClass | None] = mapped_column(
        Enum(
            DeviceClass,
            name="device_class",
            native_enum=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        )
    )
