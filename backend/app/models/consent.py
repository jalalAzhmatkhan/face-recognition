"""consents — versioned enrollment consent record (FR-ENR-08)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import UUIDPKMixin

#: Single source of truth for the consent clause version a client should
#: send in `POST /enrollments/{id}/consent` (`ConsentRequest.consent_version`,
#: see `app/schemas/enrollments.py`) when granting a *new* consent.
#:
#: EC-BE-09 (task-breakdown.md "EC-4. Keputusan Susulan") bumped this from
#: the prior value `"v1.0"` to add clauses for: synthetic masked/occlusion
#: templates (EC-TR-02/03/06), event-frames used as `recent`/probe
#: calibration templates (EC-TR-08), and the `template_candidates` buffer
#: (EC-TR-09/EC-BE-07). See `documentation/tsd/TSD-edge-cases.md` ASM-EC-05.
#:
#: Versioning is append-only via the existing mechanism — `consents` rows
#: are never mutated or deleted (see `ConsentRepository` docstring below):
#: granting a new consent simply inserts a new row with this newer version
#: string, while rows recorded under older versions (e.g. `"v1.0"`) remain
#: untouched and their grant is still honored (BE never gates access on a
#: specific `consent_version` value, only on a consent row's existence —
#: see `enrollment_service.grant_consent`). Frontend (EC-FE-05) should
#: import/reference this exact string when sending new consent grants; the
#: consent clause TEXT itself is a frontend concern (not modeled here).
CURRENT_CONSENT_VERSION = "v1.1"


class Consent(UUIDPKMixin, Base):
    __tablename__ = "consents"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    consent_version: Mapped[str] = mapped_column(String(50), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
