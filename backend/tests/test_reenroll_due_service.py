"""Unit tests for app/services/reenroll_due_service.py (EC-BE-05,
TSD-edge-cases.md A-5).

Pure unit tests, no live Postgres — fake repos in the same style as
tests/test_retention_service.py / tests/test_worker_tasks.py.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.models.enums import RecognitionConfigScope
from app.models.recognition_config import RecognitionConfig
from app.models.user import User
from app.services import reenroll_due_service as svc

NOW = datetime(2026, 9, 1, tzinfo=UTC)


class FakeUserRepo:
    def __init__(self, users: list[User]) -> None:
        self._users = {u.id: u for u in users}
        self.updated: list[User] = []

    def list_all_active_ids(self) -> list[uuid.UUID]:
        return list(self._users.keys())

    def get(self, user_id: uuid.UUID) -> User | None:
        return self._users.get(user_id)

    def update(self, user: User) -> User:
        self.updated.append(user)
        self._users[user.id] = user
        return user


class FakeEnrollmentRepo:
    def __init__(self, last_enrolled_at: dict[uuid.UUID, datetime]) -> None:
        self._last_enrolled_at = last_enrolled_at

    def list_last_enrolled_at(self) -> dict[uuid.UUID, datetime]:
        return dict(self._last_enrolled_at)


class FakeAccessEventRepo:
    def __init__(self, genuine_scores: dict[uuid.UUID, tuple[float, int]]) -> None:
        self._genuine_scores = genuine_scores
        self.since_calls: list[datetime] = []

    def genuine_score_moving_averages(
        self, *, since: datetime
    ) -> dict[uuid.UUID, tuple[float, int]]:
        self.since_calls.append(since)
        return dict(self._genuine_scores)


class FakeRecognitionConfigRepo:
    def __init__(self, global_normal_threshold: float | None = None) -> None:
        self._threshold = global_normal_threshold

    def get_by_key(self, *, scope, scope_ref, mode):
        if (
            scope == RecognitionConfigScope.GLOBAL
            and scope_ref is None
            and mode == "normal"
            and self._threshold is not None
        ):
            return RecognitionConfig(
                id=uuid.uuid4(),
                scope=RecognitionConfigScope.GLOBAL,
                scope_ref=None,
                mode="normal",
                similarity_threshold=self._threshold,
                margin=None,
                liveness_threshold=None,
                min_frames=None,
                created_by_staff_id=uuid.uuid4(),
            )
        return None


class FakeAuditRepo:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def record(self, *, actor, action, entity, payload=None):
        entry = {"actor": actor, "action": action, "entity": entity, "payload": payload}
        self.entries.append(entry)
        return entry


def _user(*, reenroll_due: bool = False) -> User:
    return User(
        id=uuid.uuid4(),
        external_ref=None,
        full_name="Test User",
        reenroll_due=reenroll_due,
        reenroll_due_reason=None,
        reenroll_due_marked_at=None,
    )


def _run(
    users: list[User],
    *,
    last_enrolled_at: dict[uuid.UUID, datetime] | None = None,
    genuine_scores: dict[uuid.UUID, tuple[float, int]] | None = None,
    global_threshold: float | None = None,
    max_age_months: int = 24,
    score_window_days: int = 90,
    score_margin: float = 0.05,
    min_events_for_score: int = 5,
    similarity_threshold_fallback: float = 0.35,
) -> tuple[svc.ReenrollDueResult, FakeUserRepo, FakeAuditRepo]:
    user_repo = FakeUserRepo(users)
    enrollment_repo = FakeEnrollmentRepo(last_enrolled_at or {})
    access_event_repo = FakeAccessEventRepo(genuine_scores or {})
    recognition_config_repo = FakeRecognitionConfigRepo(global_threshold)
    audit_repo = FakeAuditRepo()

    result = svc.evaluate_reenroll_due(
        user_repo,
        enrollment_repo,
        access_event_repo,
        recognition_config_repo,
        audit_repo,
        now=NOW,
        max_age_months=max_age_months,
        score_window_days=score_window_days,
        score_margin=score_margin,
        min_events_for_score=min_events_for_score,
        similarity_threshold_fallback=similarity_threshold_fallback,
    )
    return result, user_repo, audit_repo


def test_flags_user_meeting_age_criterion_only() -> None:
    user = _user()
    stale_enrolled_at = NOW - timedelta(days=25 * 30)

    result, user_repo, audit_repo = _run(
        [user], last_enrolled_at={user.id: stale_enrolled_at}
    )

    assert result.newly_flagged == 1
    assert user.reenroll_due is True
    assert user.reenroll_due_reason == svc.REASON_ENROLLMENT_AGE
    assert user.reenroll_due_marked_at == NOW
    assert len(audit_repo.entries) == 1
    assert audit_repo.entries[0]["action"] == svc.REENROLL_DUE_MARKED_ACTION
    assert audit_repo.entries[0]["payload"]["reasons"] == [svc.REASON_ENROLLMENT_AGE]


def test_flags_user_meeting_score_criterion_only() -> None:
    user = _user()
    recent_enrolled_at = NOW - timedelta(days=10)
    # threshold 0.35 + margin 0.05 = 0.40 ceiling; avg 0.38 < ceiling, 10 events.
    result, user_repo, audit_repo = _run(
        [user],
        last_enrolled_at={user.id: recent_enrolled_at},
        genuine_scores={user.id: (0.38, 10)},
        global_threshold=0.35,
    )

    assert result.newly_flagged == 1
    assert user.reenroll_due_reason == svc.REASON_LOW_GENUINE_SCORE


def test_flags_user_meeting_both_criteria_combines_reasons() -> None:
    user = _user()
    stale_enrolled_at = NOW - timedelta(days=25 * 30)

    result, user_repo, audit_repo = _run(
        [user],
        last_enrolled_at={user.id: stale_enrolled_at},
        genuine_scores={user.id: (0.30, 10)},
        global_threshold=0.35,
    )

    assert result.newly_flagged == 1
    assert user.reenroll_due_reason == f"{svc.REASON_ENROLLMENT_AGE}+{svc.REASON_LOW_GENUINE_SCORE}"


def test_does_not_flag_user_meeting_neither_criterion() -> None:
    user = _user()
    recent_enrolled_at = NOW - timedelta(days=10)

    result, user_repo, audit_repo = _run(
        [user],
        last_enrolled_at={user.id: recent_enrolled_at},
        genuine_scores={user.id: (0.9, 10)},
        global_threshold=0.35,
    )

    assert result.newly_flagged == 0
    assert user.reenroll_due is False
    assert audit_repo.entries == []


def test_score_criterion_ignored_below_min_event_count() -> None:
    user = _user()
    recent_enrolled_at = NOW - timedelta(days=10)

    # Would meet the score criterion (0.1 << ceiling) but only 2 events,
    # below min_events_for_score=5 -- must NOT be flagged.
    result, user_repo, audit_repo = _run(
        [user],
        last_enrolled_at={user.id: recent_enrolled_at},
        genuine_scores={user.id: (0.1, 2)},
        global_threshold=0.35,
        min_events_for_score=5,
    )

    assert result.newly_flagged == 0
    assert user.reenroll_due is False


def test_user_with_no_enrolled_session_is_not_flagged_by_age() -> None:
    user = _user()

    # No entry in last_enrolled_at at all -- never reached ENROLLED.
    result, user_repo, audit_repo = _run([user], last_enrolled_at={})

    assert result.newly_flagged == 0
    assert user.reenroll_due is False


def test_already_flagged_user_is_skipped_idempotently() -> None:
    user = _user(reenroll_due=True)
    user.reenroll_due_reason = "video_retention_expired"
    user.reenroll_due_marked_at = NOW - timedelta(days=1)
    stale_enrolled_at = NOW - timedelta(days=25 * 30)

    result, user_repo, audit_repo = _run(
        [user], last_enrolled_at={user.id: stale_enrolled_at}
    )

    assert result.newly_flagged == 0
    assert result.already_flagged_skipped == 1
    assert audit_repo.entries == []
    # Original reason/timestamp from the other producer must be untouched.
    assert user.reenroll_due_reason == "video_retention_expired"


def test_running_twice_produces_no_duplicate_audit() -> None:
    user = _user()
    stale_enrolled_at = NOW - timedelta(days=25 * 30)

    result1, user_repo, audit_repo = _run(
        [user], last_enrolled_at={user.id: stale_enrolled_at}
    )
    assert result1.newly_flagged == 1
    assert len(audit_repo.entries) == 1

    # Second run reuses the SAME user object (now reenroll_due=True) and a
    # fresh audit repo to prove the second run writes nothing new.
    result2, user_repo2, audit_repo2 = _run(
        [user], last_enrolled_at={user.id: stale_enrolled_at}
    )
    assert result2.newly_flagged == 0
    assert result2.already_flagged_skipped == 1
    assert audit_repo2.entries == []


def test_similarity_threshold_falls_back_to_settings_default_when_no_global_config() -> None:
    user = _user()
    recent_enrolled_at = NOW - timedelta(days=10)

    result, _, _ = _run(
        [user],
        last_enrolled_at={user.id: recent_enrolled_at},
        genuine_scores={user.id: (0.9, 10)},
        global_threshold=None,
        similarity_threshold_fallback=0.42,
    )

    assert result.resolved_similarity_threshold == 0.42


def test_similarity_threshold_uses_global_recognition_config_when_present() -> None:
    user = _user()
    recent_enrolled_at = NOW - timedelta(days=10)

    result, _, _ = _run(
        [user],
        last_enrolled_at={user.id: recent_enrolled_at},
        genuine_scores={user.id: (0.9, 10)},
        global_threshold=0.5,
        similarity_threshold_fallback=0.35,
    )

    assert result.resolved_similarity_threshold == 0.5


def test_evaluated_active_users_counts_all_active_users() -> None:
    users = [_user(), _user(), _user()]

    result, _, _ = _run(users)

    assert result.evaluated_active_users == 3
