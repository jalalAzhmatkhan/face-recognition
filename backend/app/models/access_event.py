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
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import AccessDecision


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
