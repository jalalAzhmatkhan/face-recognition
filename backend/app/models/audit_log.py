"""audit_logs — append-only audit trail (TSD §4/§6, NFR-SEC-05).

No UPDATE/DELETE is exposed anywhere in the model or repository layer — the
repository layer (app/repositories/) MUST only ever INSERT/SELECT this table.
DB-level protection (revoke UPDATE/DELETE from the application role) is applied
in the `_role_separation` migration; see backend/README.md.
"""

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import UUIDPKMixin


class AuditLog(UUIDPKMixin, Base):
    __tablename__ = "audit_logs"

    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    entity: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONB)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
