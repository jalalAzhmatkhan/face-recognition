"""identity_similarity_flags — high-similarity pairs between two distinct
identities (EC-BE-04, TSD-edge-cases.md D-4.4/D-10, REC 13).

Written by the enrollment/re-embed pipeline (TR-03/`GALLERY_REEMBED`, a
later ai-training task) whenever a newly-embedded template's similarity to
another identity's gallery exceeds `(tau - margin_hs)` — a signal that two
different enrolled people (e.g. identical twins, close look-alikes) may be
confusable by the matcher. Consumed by:
  - the D-6 adaptive-template guard (`app/services/...` adaptive update, a
    later task): a user appearing here is BLOCKED from adaptive template
    promotion (poisoning-target mitigation, OQ-7 guard #3);
  - policy: [AKSES] requires a second factor, [ABSENSI] requires UI
    confirmation + photo log for a flagged pair (D-4.4).

This table has no dedicated HTTP endpoint in EC-BE-04 (it is written by a
pipeline, not edited by staff) — only the repository/service CRUD primitives
a later task wires up to an endpoint or an internal caller.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import UUIDPKMixin


class IdentitySimilarityFlag(UUIDPKMixin, Base):
    __tablename__ = "identity_similarity_flags"
    __table_args__ = (
        CheckConstraint("user_a_id <> user_b_id", name="ck_identity_similarity_flags_distinct"),
    )

    # Unordered pair: no canonical "a < b" ordering is enforced at the DB
    # level (the writing pipeline may record either order), so callers that
    # need "all flags involving user X" must query both columns — see
    # app/repositories/identity_similarity_flags.py::list_for_user.
    user_a_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_b_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
    flagged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Set once an operator has reviewed the pair (D-4.4 policy response
    # applied, false-positive dismissed, etc.). NULL = still open/unreviewed.
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"IdentitySimilarityFlag(id={self.id!r}, user_a_id={self.user_a_id!r}, "
            f"user_b_id={self.user_b_id!r}, score={self.score!r})"
        )
