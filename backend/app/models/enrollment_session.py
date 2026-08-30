"""enrollment_sessions — enrollment state machine (FSD-AI.md §8, FR-ENR-*)."""

import uuid

from sqlalchemy import Enum, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import EnrollmentState
from app.models.mixins import TimestampMixin, UUIDPKMixin


class EnrollmentSession(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "enrollment_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    state: Mapped[EnrollmentState] = mapped_column(
        Enum(EnrollmentState, name="enrollment_state", native_enum=True),
        nullable=False,
        default=EnrollmentState.CREATED,
        server_default=EnrollmentState.CREATED.value,
    )
    # QC results (FR-ENR-06): machine-readable pass/fail reasons, pose coverage, etc.
    qc_report: Mapped[dict | None] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff_accounts.id", ondelete="SET NULL")
    )
