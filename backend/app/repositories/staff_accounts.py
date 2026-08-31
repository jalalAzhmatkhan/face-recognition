"""Repository for `staff_accounts` (BE-03).

Mirrors the minimal get/list pattern established by `app/repositories/users.py`
(BE-02) — no business logic here, just data access.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import StaffRole
from app.models.staff_account import StaffAccount


class StaffAccountRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, staff_id: uuid.UUID) -> StaffAccount | None:
        return self._session.get(StaffAccount, staff_id)

    def get_by_email(self, email: str) -> StaffAccount | None:
        stmt = select(StaffAccount).where(StaffAccount.email == email)
        return self._session.scalars(stmt).one_or_none()

    def exists_by_role(self, role: StaffRole) -> bool:
        """Used by the first-run bootstrap flow (BE-03 follow-up) to check
        whether any staff account of a given role already exists — e.g.
        "has an ADMIN been created yet" — without loading a full row."""
        stmt = select(StaffAccount.id).where(StaffAccount.role == role).limit(1)
        return self._session.scalars(stmt).first() is not None

    def create(self, account: StaffAccount) -> StaffAccount:
        self._session.add(account)
        self._session.commit()
        self._session.refresh(account)
        return account
