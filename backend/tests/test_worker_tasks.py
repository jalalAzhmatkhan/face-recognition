"""Unit tests for app/worker/tasks.py (BE-07, NFR-OPS-02).

No real Redis/Postgres involved:
  - `celery_app.conf.task_always_eager = True` runs tasks synchronously
    in-process (still exercises Celery's real retry/on_failure machinery),
  - the DB layer is a `FakeEnrollmentRepo`/`FakeAuditRepo` pair (same style
    as `tests/test_media_service.py`) rather than a live Session, and
  - `DeadLetterTask.on_failure` (which normally opens its own DB session
    via `get_sessionmaker()`) is exercised by monkeypatching
    `app.worker.tasks.get_sessionmaker` to hand back a fake session/repo,
    so no `DATABASE_URL` is needed.
"""

import uuid
from datetime import UTC, datetime

import pytest
from celery import Task

from app.models.enrollment_session import EnrollmentSession
from app.models.enums import EnrollmentState
from app.worker import tasks as worker_tasks
from app.worker.celery_app import celery_app


class FakeEnrollmentRepo:
    def __init__(self, session: EnrollmentSession | None) -> None:
        self._session = session

    def get(self, session_id: uuid.UUID) -> EnrollmentSession | None:
        if self._session is None or session_id != self._session.id:
            return None
        return self._session


class FakeAuditRepo:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def record(self, *, actor, action, entity, payload=None):
        entry = {"actor": actor, "action": action, "entity": entity, "payload": payload}
        self.entries.append(entry)
        return entry


def _session(state: EnrollmentState) -> EnrollmentSession:
    now = datetime.now(UTC)
    return EnrollmentSession(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        state=state,
        qc_report=None,
        created_by=uuid.uuid4(),
        created_at=now,
        updated_at=now,
    )


# --- _run_enrollment_qc_stub (core logic, no Celery involved) --------------


def test_qc_stub_executes_and_audits_when_qc_running() -> None:
    session = _session(EnrollmentState.QC_RUNNING)
    enrollment_repo = FakeEnrollmentRepo(session)
    audit_repo = FakeAuditRepo()

    outcome = worker_tasks._run_enrollment_qc_stub(enrollment_repo, audit_repo, session.id)

    assert outcome == "executed"
    assert len(audit_repo.entries) == 1
    entry = audit_repo.entries[0]
    assert entry["action"] == "job.qc_stub_executed"
    assert entry["entity"] == f"enrollment_session:{session.id}"
    assert entry["payload"]["session_id"] == str(session.id)
    # Must NOT touch session.state — that's TR-02's call, not BE-07's.
    assert session.state == EnrollmentState.QC_RUNNING


@pytest.mark.parametrize(
    "state",
    [
        EnrollmentState.QC_PASSED,
        EnrollmentState.REJECTED_QUALITY,
        EnrollmentState.CANCELLED,
        EnrollmentState.CREATED,
    ],
)
def test_qc_stub_is_idempotent_noop_when_not_qc_running(state: EnrollmentState) -> None:
    """Duplicate job delivery after the session already moved on: no-op,
    not an error, and no `job.qc_stub_executed` entry (only a skip log)."""
    session = _session(state)
    enrollment_repo = FakeEnrollmentRepo(session)
    audit_repo = FakeAuditRepo()

    outcome = worker_tasks._run_enrollment_qc_stub(enrollment_repo, audit_repo, session.id)

    assert outcome == "skipped_wrong_state"
    assert len(audit_repo.entries) == 1
    entry = audit_repo.entries[0]
    assert entry["action"] == "job.qc_stub_skipped"
    assert entry["payload"]["reason"] == "not_qc_running"
    assert entry["payload"]["state"] == state.value
    assert not any(e["action"] == "job.qc_stub_executed" for e in audit_repo.entries)


def test_qc_stub_skips_when_session_not_found() -> None:
    enrollment_repo = FakeEnrollmentRepo(None)
    audit_repo = FakeAuditRepo()
    missing_id = uuid.uuid4()

    outcome = worker_tasks._run_enrollment_qc_stub(enrollment_repo, audit_repo, missing_id)

    assert outcome == "skipped_not_found"
    assert audit_repo.entries[0]["action"] == "job.qc_stub_skipped"
    assert audit_repo.entries[0]["payload"]["reason"] == "session_not_found"


# --- retry config declared on the real Celery task -------------------------


def test_run_enrollment_qc_has_expected_retry_config() -> None:
    task = celery_app.tasks["app.worker.tasks.run_enrollment_qc"]
    assert task.autoretry_for == worker_tasks.RETRYABLE_EXCEPTIONS
    assert task.retry_backoff is True
    assert task.max_retries == 5
    assert issubclass(task.__class__, worker_tasks.DeadLetterTask)


# --- end-to-end via eager mode (Celery's real retry/on_failure machinery) --


@pytest.fixture
def eager_celery():
    original_eager = celery_app.conf.task_always_eager
    original_propagates = celery_app.conf.task_eager_propagates
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False
    yield celery_app
    celery_app.conf.task_always_eager = original_eager
    celery_app.conf.task_eager_propagates = original_propagates


class _FakeDbSession:
    """Stands in for the SQLAlchemy `Session` the real task/on_failure would
    open via `get_sessionmaker()`. `AuditLogRepository` only ever calls
    `add`/`commit`/`refresh` on it (see app/repositories/audit_logs.py)."""

    def __init__(self, sink: list) -> None:
        self._sink = sink

    def add(self, entry) -> None:
        self._sink.append(entry)

    def commit(self) -> None:
        pass

    def refresh(self, entry) -> None:
        pass

    def close(self) -> None:
        pass


def test_run_enrollment_qc_end_to_end_success(monkeypatch, eager_celery) -> None:
    session = _session(EnrollmentState.QC_RUNNING)
    enrollment_repo = FakeEnrollmentRepo(session)
    audit_sink: list = []

    monkeypatch.setattr(worker_tasks, "EnrollmentSessionRepository", lambda db: enrollment_repo)
    monkeypatch.setattr(
        worker_tasks, "get_sessionmaker", lambda: lambda: _FakeDbSession(audit_sink)
    )

    result = worker_tasks.run_enrollment_qc.apply(args=[str(session.id)])

    assert result.state == "SUCCESS"
    assert result.result == "executed"
    assert len(audit_sink) == 1
    assert audit_sink[0].action == "job.qc_stub_executed"


def test_dead_letter_written_after_retries_exhausted(monkeypatch, eager_celery) -> None:
    """A task that always raises a retryable exception ends up, after
    `max_retries` is exhausted, with one `job.dead_letter` audit_logs entry —
    this is BE-07's DLQ-observability requirement (NFR-OPS-02)."""
    audit_sink: list = []
    monkeypatch.setattr(
        worker_tasks, "get_sessionmaker", lambda: lambda: _FakeDbSession(audit_sink)
    )

    call_count = {"n": 0}

    @celery_app.task(
        name="test.always_fails",
        base=worker_tasks.DeadLetterTask,
        bind=True,
        autoretry_for=(ConnectionError,),
        retry_backoff=False,
        max_retries=2,
    )
    def always_fails(self: Task) -> None:
        call_count["n"] += 1
        raise ConnectionError("simulated transient broker/DB blip")

    result = always_fails.apply()

    assert result.state == "FAILURE"
    assert call_count["n"] == 3  # initial attempt + 2 retries
    dead_letters = [e for e in audit_sink if e.action == worker_tasks.DEAD_LETTER_ACTION]
    assert len(dead_letters) == 1
    assert dead_letters[0].payload["task"] == "test.always_fails"
    assert dead_letters[0].payload["exception_type"] == "ConnectionError"
