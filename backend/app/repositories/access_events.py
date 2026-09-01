"""Repository for `access_events` (BE-10, TSD §4/§7, FR-INF-01..06, FR-MON-01)."""

import uuid
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models.access_event import AccessEvent
from app.models.enums import AccessDecision


class AccessEventRepository:
    """Thin data-access wrapper around a SQLAlchemy `Session`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, event: AccessEvent) -> AccessEvent:
        self._session.add(event)
        self._session.commit()
        self._session.refresh(event)
        return event

    def list(
        self,
        *,
        device_id: uuid.UUID | None = None,
        decision: AccessDecision | None = None,
        occurred_from: datetime | None = None,
        occurred_to: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AccessEvent]:
        stmt = (
            select(AccessEvent)
            .order_by(AccessEvent.occurred_at.desc())
            .limit(limit)
            .offset(offset)
        )
        stmt = self._apply_filters(stmt, device_id, decision, occurred_from, occurred_to)
        return list(self._session.scalars(stmt))

    def count(
        self,
        *,
        device_id: uuid.UUID | None = None,
        decision: AccessDecision | None = None,
        occurred_from: datetime | None = None,
        occurred_to: datetime | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(AccessEvent)
        stmt = self._apply_filters(stmt, device_id, decision, occurred_from, occurred_to)
        return self._session.scalar(stmt) or 0

    def genuine_score_moving_averages(
        self, *, since: datetime
    ) -> dict[uuid.UUID, tuple[float, int]]:
        """Per-user `(avg(similarity), count)` over GENUINE accept events
        (`decision=GRANTED`, `matched_user_id IS NOT NULL`,
        `similarity IS NOT NULL`) at/after `since` (EC-BE-05, TSD A-5 score
        criterion — "moving-average skor genuine ... dari log funnel D-1").

        One aggregate query for ALL users at once, same rationale as
        `EnrollmentSessionRepository.list_last_enrolled_at` — the beat job
        must not do a per-user query over a table that can hold months of
        `access_events` (partitioned by `occurred_at`, but still large).
        A user absent from the returned mapping has no GENUINE accepts in
        the window at all, which the service layer treats as "not enough
        data to evaluate the score criterion" (same stance as a user with
        fewer than `reenroll_due_min_events_for_score` events).
        """
        stmt = (
            select(
                AccessEvent.matched_user_id,
                func.avg(AccessEvent.similarity),
                func.count(AccessEvent.id),
            )
            .where(
                AccessEvent.decision == AccessDecision.GRANTED,
                AccessEvent.matched_user_id.is_not(None),
                AccessEvent.similarity.is_not(None),
                AccessEvent.occurred_at >= since,
            )
            .group_by(AccessEvent.matched_user_id)
        )
        return {
            user_id: (float(avg_score), int(count))
            for user_id, avg_score, count in self._session.execute(stmt).all()
        }

    @staticmethod
    def _apply_filters(
        stmt: Select,
        device_id: uuid.UUID | None,
        decision: AccessDecision | None,
        occurred_from: datetime | None,
        occurred_to: datetime | None,
    ) -> Select:
        if device_id is not None:
            stmt = stmt.where(AccessEvent.device_id == device_id)
        if decision is not None:
            stmt = stmt.where(AccessEvent.decision == decision)
        if occurred_from is not None:
            stmt = stmt.where(AccessEvent.occurred_at >= occurred_from)
        if occurred_to is not None:
            stmt = stmt.where(AccessEvent.occurred_at <= occurred_to)
        return stmt
