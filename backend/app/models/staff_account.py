"""staff_accounts — operators/admins with OIDC-backed RBAC (TSD §4, FR-USR-02)."""

from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import StaffRole
from app.models.mixins import CreatedAtMixin, UUIDPKMixin


class StaffAccount(UUIDPKMixin, CreatedAtMixin, Base):
    __tablename__ = "staff_accounts"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    role: Mapped[StaffRole] = mapped_column(
        Enum(StaffRole, name="staff_role", native_enum=True), nullable=False
    )
    # OIDC federation is a future phase (not BE-03 scope) — nullable so local
    # password-auth accounts (BE-03) can exist without an external subject.
    oidc_sub: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True, index=True
    )
    # BE-03: local email+password auth. Nullable so an account created only
    # for future OIDC federation (no local password) remains representable.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"StaffAccount(id={self.id!r}, email={self.email!r}, role={self.role!r})"
