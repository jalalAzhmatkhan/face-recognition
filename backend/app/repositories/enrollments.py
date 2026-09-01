"""Repository for `enrollment_sessions` (BE-05).

Mirrors the minimal get/list/create/update pattern established by
`app/repositories/users.py` — no business logic (state-machine validation,
consent gating) here, just data access.
"""

import uuid
from datetime import datetime

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

    def list_last_enrolled_at(self) -> dict[uuid.UUID, datetime]:
        """Map of `user_id -> MAX(updated_at)` across that user's `ENROLLED`
        sessions (EC-BE-05, TSD A-5 age criterion).

        One aggregate query for ALL users at once (not per-user `get`/`list`
        calls) so the beat job in `app/services/reenroll_due_service.py`
        stays a fixed, small number of round-trips regardless of user count.
        A user absent from the returned mapping has never reached `ENROLLED`
        at all and is therefore not evaluated by the age criterion (nothing
        to anchor "how long ago" on) — same "no anchor, skip" stance as
        `retention_service.backfill_retention_expiry`'s `skipped_not_enrolled`
        case.
        """
        stmt = (
            select(EnrollmentSession.user_id, func.max(EnrollmentSession.updated_at))
            .where(EnrollmentSession.state == EnrollmentState.ENROLLED)
            .group_by(EnrollmentSession.user_id)
        )
        return dict(self._session.execute(stmt).all())
