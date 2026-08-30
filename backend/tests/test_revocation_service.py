"""Unit tests for app/services/revocation_service.py (BE-08, FR-ENR-09).

Only the *synchronous* half is exercised here: state transition, user
offboard, audit entry, and best-effort job dispatch (mocked — no Celery/
Redis involved). The async cleanup job itself is tested in
tests/test_worker_tasks.py. Role enforcement (ADMIN only) is a router-level
concern (`require_role`), tested in tests/test_enrollments_router.py.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.models.enrollment_session import EnrollmentSession
from app.models.enums import EnrollmentState, UserStatus
from app.models.user import User
from app.services import enrollment_service, revocation_service
from app.services import enrollment_state_machine as fsm


class FakeEnrollmentRepo:
    def __init__(self, session: EnrollmentSession | None) -> None:
        self._session = session

    def get(self, session_id: uuid.UUID) -> EnrollmentSession | None:
        if self._session is None or session_id != self._session.id:
            return None
        return self._session

    def update(self, enrollment: EnrollmentSession) -> EnrollmentSession:
        enrollment.updated_at = datetime.now(UTC)
        self._session = enrollment
        return enrollment


class FakeUserRepo:
    def __init__(self, user: User | None) -> None:
        self._user = user
        self.update_calls: list[User] = []

    def get(self, user_id: uuid.UUID) -> User | None:
        if self._user is None or user_id != self._user.id:
            return None
        return self._user

    def update(self, user: User) -> User:
        self.update_calls.append(user)
        self._user = user
        return user


class FakeAuditRepo:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def record(self, *, actor, action, entity, payload=None):
        entry = {"actor": actor, "action": action, "entity": entity, "payload": payload}
        self.entries.append(entry)
        return entry


def _session(state: EnrollmentState, user_id: uuid.UUID | None = None) -> EnrollmentSession:
    now = datetime.now(UTC)
    return EnrollmentSession(
        id=uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
        state=state,
        qc_report=None,
        created_by=uuid.uuid4(),
        created_at=now,
        updated_at=now,
    )


def _user(user_id: uuid.UUID, status: UserStatus = UserStatus.ACTIVE) -> User:
    now = datetime.now(UTC)
    return User(
        id=user_id,
        external_ref=f"EMP-{uuid.uuid4().hex[:6]}",
        full_name="Test Person",
        status=status,
        created_at=now,
        updated_at=now,
    )


def test_revoke_enrollment_succeeds_from_enrolled(monkeypatch) -> None:
    session = _session(EnrollmentState.ENROLLED)
    user = _user(session.user_id, UserStatus.ACTIVE)
    enrollment_repo = FakeEnrollmentRepo(session)
    user_repo = FakeUserRepo(user)
    audit_repo = FakeAuditRepo()

    dispatched: list[uuid.UUID] = []
    monkeypatch.setattr(
        revocation_service.revocation_queue_service,
        "enqueue_revocation_cleanup",
        lambda session_id: dispatched.append(session_id),
    )

    result = revocation_service.revoke_enrollment(
        enrollment_repo, user_repo, audit_repo, session_id=session.id, actor="staff:1"
    )

    assert result.state == EnrollmentState.REVOKED
    assert user.status == UserStatus.OFFBOARDED
    assert user_repo.update_calls == [user]
    assert dispatched == [session.id]

    actions = [e["action"] for e in audit_repo.entries]
    assert revocation_service.REVOKE_INITIATED_ACTION in actions
    initiated = next(
        e for e in audit_repo.entries if e["action"] == revocation_service.REVOKE_INITIATED_ACTION
    )
    assert initiated["payload"]["from"] == "ENROLLED"
    assert initiated["payload"]["to"] == "REVOKED"


def test_revoke_enrollment_is_noop_on_user_offboard_if_already_offboarded(monkeypatch) -> None:
    session = _session(EnrollmentState.ENROLLED)
    user = _user(session.user_id, UserStatus.OFFBOARDED)
    enrollment_repo = FakeEnrollmentRepo(session)
    user_repo = FakeUserRepo(user)
    audit_repo = FakeAuditRepo()
    monkeypatch.setattr(
        revocation_service.revocation_queue_service, "enqueue_revocation_cleanup", lambda _id: None
    )

    revocation_service.revoke_enrollment(
        enrollment_repo, user_repo, audit_repo, session_id=session.id, actor="staff:1"
    )

    assert user_repo.update_calls == []  # already OFFBOARDED, no redundant write


@pytest.mark.parametrize(
    "state",
    [
        EnrollmentState.CREATED,
        EnrollmentState.CONSENTED,
        EnrollmentState.CAPTURING,
        EnrollmentState.CAPTURED,
        EnrollmentState.QC_RUNNING,
        EnrollmentState.REJECTED_QUALITY,
        EnrollmentState.QC_PASSED,
        EnrollmentState.EMBEDDING,
        EnrollmentState.CANCELLED,
        EnrollmentState.REVOKED,
    ],
)
def test_revoke_enrollment_rejected_unless_enrolled(monkeypatch, state: EnrollmentState) -> None:
    session = _session(state)
    user = _user(session.user_id)
    enrollment_repo = FakeEnrollmentRepo(session)
    user_repo = FakeUserRepo(user)
    audit_repo = FakeAuditRepo()
    dispatched: list[uuid.UUID] = []
    monkeypatch.setattr(
        revocation_service.revocation_queue_service,
        "enqueue_revocation_cleanup",
        lambda session_id: dispatched.append(session_id),
    )

    with pytest.raises(fsm.IllegalTransitionError):
        revocation_service.revoke_enrollment(
            enrollment_repo, user_repo, audit_repo, session_id=session.id, actor="staff:1"
        )

    assert session.state == state  # untouched
    assert user.status != UserStatus.OFFBOARDED or state == EnrollmentState.REVOKED
    assert dispatched == []  # never reached the dispatch


def test_revoke_enrollment_raises_not_found_for_unknown_session() -> None:
    enrollment_repo = FakeEnrollmentRepo(None)
    user_repo = FakeUserRepo(None)
    audit_repo = FakeAuditRepo()

    with pytest.raises(enrollment_service.EnrollmentNotFoundError):
        revocation_service.revoke_enrollment(
            enrollment_repo, user_repo, audit_repo, session_id=uuid.uuid4(), actor="staff:1"
        )


def test_revoke_enrollment_dispatch_failure_does_not_break_sync_transaction(monkeypatch) -> None:
    """Mirrors qc_queue's broker-down tolerance: a dispatch exception inside
    `enqueue_revocation_cleanup` itself is already swallowed there (see
    app/services/revocation_queue.py), so calling the real function (not a
    mock) with a broken import must not raise out of `revoke_enrollment`."""
    session = _session(EnrollmentState.ENROLLED)
    user = _user(session.user_id)
    enrollment_repo = FakeEnrollmentRepo(session)
    user_repo = FakeUserRepo(user)
    audit_repo = FakeAuditRepo()

    def _broken_delay(*args, **kwargs):
        raise ConnectionError("broker down")

    class _FakeTask:
        delay = staticmethod(_broken_delay)

    monkeypatch.setattr(
        "app.worker.tasks.revoke_enrollment_cleanup", _FakeTask(), raising=False
    )

    result = revocation_service.revoke_enrollment(
        enrollment_repo, user_repo, audit_repo, session_id=session.id, actor="staff:1"
    )

    assert result.state == EnrollmentState.REVOKED
    assert user.status == UserStatus.OFFBOARDED
