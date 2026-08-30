"""Repository for `staff_accounts` (BE-03).

Mirrors the minimal get/list pattern established by `app/repositories/users.py`
(BE-02) — no business logic here, just data access.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.staff_account import StaffAccount


class StaffAccountRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, staff_id: uuid.UUID) -> StaffAccount | None:
        return self._session.get(StaffAccount, staff_id)

    def get_by_email(self, email: str) -> StaffAccount | None:
        stmt = select(StaffAccount).where(StaffAccount.email == email)
        return self._session.scalars(stmt).one_or_none()
