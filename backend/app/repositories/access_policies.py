"""Repository for `access_policies` (BE-10, TSD §4/§7).

Mirrors the minimal CRUD pattern established by `app/repositories/users.py` /
`app/repositories/devices.py` — no business logic here, just data access.

`from __future__ import annotations` (postponed evaluation, PEP 563) is used
here because this class defines a method literally named `list` — without
it, evaluating a LATER method's `-> list[AccessPolicy]` return annotation at
class-body-exec time would resolve `list` to that earlier method object
(already bound in the class namespace) instead of the builtin, raising
`TypeError: 'function' object is not subscriptable` at import time.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.access_policy import AccessPolicy


class AccessPolicyRepository:
    """Thin data-access wrapper around a SQLAlchemy `Session`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, policy_id: uuid.UUID) -> AccessPolicy | None:
        return self._session.get(AccessPolicy, policy_id)

    def list(
        self,
        *,
        user_id: uuid.UUID | None = None,
        door_group: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AccessPolicy]:
        stmt = select(AccessPolicy).order_by(AccessPolicy.door_group).limit(limit).offset(offset)
        if user_id is not None:
            stmt = stmt.where(AccessPolicy.user_id == user_id)
        if door_group is not None:
            stmt = stmt.where(AccessPolicy.door_group == door_group)
        return list(self._session.scalars(stmt))

    def count(
        self, *, user_id: uuid.UUID | None = None, door_group: str | None = None
    ) -> int:
        stmt = select(func.count()).select_from(AccessPolicy)
        if user_id is not None:
            stmt = stmt.where(AccessPolicy.user_id == user_id)
        if door_group is not None:
            stmt = stmt.where(AccessPolicy.door_group == door_group)
        return self._session.scalar(stmt) or 0

    def list_for_user(self, user_id: uuid.UUID) -> list[AccessPolicy]:
        """All policies directly scoped to `user_id`.

        v1 limitation (documented in app/services/policy_cache.py): there is
        no user<->group membership source in the current schema, so
        `group_id`-scoped policies are NOT resolved here. A policy row that
        only sets `group_id` is invisible to snapshot building until a group
        membership model exists.
        """
        stmt = select(AccessPolicy).where(AccessPolicy.user_id == user_id)
        return list(self._session.scalars(stmt))

    def create(self, policy: AccessPolicy) -> AccessPolicy:
        self._session.add(policy)
        self._session.commit()
        self._session.refresh(policy)
        return policy

    def update(self, policy: AccessPolicy) -> AccessPolicy:
        self._session.add(policy)
        self._session.commit()
        self._session.refresh(policy)
        return policy

    def delete(self, policy: AccessPolicy) -> None:
        self._session.delete(policy)
        self._session.commit()
