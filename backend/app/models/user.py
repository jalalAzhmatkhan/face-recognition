"""users — enrolled/authorized identities (TSD §4)."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import UserStatus
from app.models.mixins import TimestampMixin, UUIDPKMixin


class User(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "users"

    external_ref: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus, name="user_status", native_enum=True),
        nullable=False,
        default=UserStatus.ACTIVE,
        server_default=UserStatus.ACTIVE.value,
    )
    # EC-BE-05 (TSD-edge-cases.md A-5/D-9): re-enrollment-due policy flag.
    # See migrations/versions/d8e1f3a6c2b5_users_reenroll_due.py for the full
    # design rationale (why this lives on `users`, not `enrollment_sessions`)
    # and app/services/reenroll_due_service.py for what sets it.
    reenroll_due: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    reenroll_due_reason: Mapped[str | None] = mapped_column(String(64))
    reenroll_due_marked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"User(id={self.id!r}, status={self.status!r})"
