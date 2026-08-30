"""Repository for `enrollment_sessions` (BE-05).

Mirrors the minimal get/list/create/update pattern established by
`app/repositories/users.py` — no business logic (state-machine validation,
consent gating) here, just data access.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enrollment_session import EnrollmentSession
from app.models.enums import EnrollmentState


class EnrollmentSessionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, session_id: uuid.UUID) -> EnrollmentSession | None:
        return self._session.get(EnrollmentSession, session_id)

    def list(
        self,
        *,
        user_id: uuid.UUID | None = None,
        state: EnrollmentState | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[EnrollmentSession]:
        stmt = (
            select(EnrollmentSession)
            .order_by(EnrollmentSession.created_at)
            .limit(limit)
            .offset(offset)
        )
        if user_id is not None:
            stmt = stmt.where(EnrollmentSession.user_id == user_id)
        if state is not None:
            stmt = stmt.where(EnrollmentSession.state == state)
        return list(self._session.scalars(stmt))

    def count(
        self,
        *,
        user_id: uuid.UUID | None = None,
        state: EnrollmentState | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(EnrollmentSession)
        if user_id is not None:
            stmt = stmt.where(EnrollmentSession.user_id == user_id)
        if state is not None:
            stmt = stmt.where(EnrollmentSession.state == state)
        return self._session.scalar(stmt) or 0

    def create(self, enrollment: EnrollmentSession) -> EnrollmentSession:
        self._session.add(enrollment)
        self._session.commit()
        self._session.refresh(enrollment)
        return enrollment

    def update(self, enrollment: EnrollmentSession) -> EnrollmentSession:
        self._session.add(enrollment)
        self._session.commit()
        self._session.refresh(enrollment)
        return enrollment
