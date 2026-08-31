"""Repository for `password_reset_tokens` (BE-03 follow-up).

Mirrors the minimal pattern established by `app/repositories/staff_accounts.py`.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.password_reset_token import PasswordResetToken


class PasswordResetTokenRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, token_id: uuid.UUID) -> PasswordResetToken | None:
        return self._session.get(PasswordResetToken, token_id)

    def create(self, token: PasswordResetToken) -> PasswordResetToken:
        self._session.add(token)
        self._session.commit()
        self._session.refresh(token)
        return token

    def mark_used(self, token: PasswordResetToken) -> None:
        token.used_at = datetime.now(UTC)
        self._session.commit()
