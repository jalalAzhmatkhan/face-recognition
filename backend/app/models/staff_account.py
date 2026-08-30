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
    oidc_sub: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"StaffAccount(id={self.id!r}, email={self.email!r}, role={self.role!r})"
