"""Repository for `users` — reference pattern for later repositories (BE-04+).

Kept intentionally minimal (get/list only) for BE-02; full CRUD lands in BE-04.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import UserStatus
from app.models.user import User


class UserRepository:
    """Thin data-access wrapper around a SQLAlchemy `Session`.

    No business logic here (that belongs in app/services/) — just queries.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, user_id: uuid.UUID) -> User | None:
        return self._session.get(User, user_id)

    def list(
        self,
        *,
        status: UserStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[User]:
        stmt = select(User).order_by(User.created_at).limit(limit).offset(offset)
        if status is not None:
            stmt = stmt.where(User.status == status)
        return list(self._session.scalars(stmt))
