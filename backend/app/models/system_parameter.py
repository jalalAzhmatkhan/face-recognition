"""system_parameters — ADMIN-tunable operational knobs, exposed via the
"System Parameter" admin menu.

Deliberately a generic `key -> jsonb value` table (not one column per
knob): the first (and, as of this table's introduction, only) consumer is
`enrollment_capture_quality` (min sharpness / brightness range for the
Enrollment capture wizard's live preflight AND the server-side QC gate —
see `app/services/system_parameter_service.py`), but this shape lets a
future System Parameter without its own migration.

A row is entirely OPTIONAL: `app/services/system_parameter_service.py`
falls back to a built-in default whenever no row exists for a key yet, so
a fresh deploy (or a key nobody has ever saved) behaves exactly as if this
table didn't exist. `ai-training`'s QC worker reads this table directly
(read-only, via the widened `ai_training_embeddings_write` role — see
migration `d1e5c8a3f7b2`) to apply the SAME effective thresholds the admin
menu configured, rather than each service keeping its own independent copy.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SystemParameter(Base):
    __tablename__ = "system_parameters"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff_accounts.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"SystemParameter(key={self.key!r})"
