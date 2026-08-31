"""password_reset_tokens — single-use forgot-password tokens (BE-03 follow-up)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import CreatedAtMixin, UUIDPKMixin


class PasswordResetToken(UUIDPKMixin, CreatedAtMixin, Base):
    __tablename__ = "password_reset_tokens"

    # Each row is single-use and minted fresh per forgot-password request, so
    # the row's own `id` (UUIDPKMixin) doubles as the "token id" half of the
    # issued `<token_id>.<secret>` string — no separate lookup column needed
    # (unlike `devices.auth_credential_ref`, which must survive rotation).
    staff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("staff_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Argon2id hash of the secret half — mirrors `staff_accounts.password_hash`
    # / `devices.credential_hash`. Never the plaintext secret.
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Set once the token is consumed by a successful reset — checked so a
    # token can never be replayed a second time even before it expires.
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
