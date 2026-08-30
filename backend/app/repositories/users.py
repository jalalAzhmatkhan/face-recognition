"""Repository for `users` — reference pattern for later repositories (BE-04+).

Full CRUD (BE-04): `get`/`list` from BE-02 plus `create`/`update`/`count`/
`get_by_external_ref` needed by the users router + service layer.
"""

import uuid

from sqlalchemy import func, select
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

    def get_by_external_ref(self, external_ref: str) -> User | None:
        stmt = select(User).where(User.external_ref == external_ref)
        return self._session.scalars(stmt).one_or_none()

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

    def count(self, *, status: UserStatus | None = None) -> int:
        stmt = select(func.count()).select_from(User)
        if status is not None:
            stmt = stmt.where(User.status == status)
        return self._session.scalar(stmt) or 0

    def create(self, user: User) -> User:
        self._session.add(user)
        self._session.commit()
        self._session.refresh(user)
        return user

    def update(self, user: User) -> User:
        self._session.add(user)
        self._session.commit()
        self._session.refresh(user)
        return user
