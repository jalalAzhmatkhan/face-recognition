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
from app.models.enums import EnrollmentState, MediaKind, MediaObjectStatus, UserStatus
from app.models.face_embedding import FaceEmbedding
from app.models.media_object import MediaObject
from app.models.user import User
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


# --- revoke_enrollment_cleanup (BE-08, FR-ENR-09/NFR-SEC-03/ASM-12) --------


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


class FakeMediaRepo:
    def __init__(self, media: list[MediaObject]) -> None:
        self._media = list(media)
        self.deleted: list[MediaObject] = []

    def list_for_session(self, session_id: uuid.UUID) -> list[MediaObject]:
        return [m for m in self._media if m.session_id == session_id]

    def delete(self, media: MediaObject) -> None:
        self._media = [m for m in self._media if m.id != media.id]
        self.deleted.append(media)


class FakeEmbeddingRepo:
    def __init__(self, embeddings: list[FaceEmbedding]) -> None:
        self._embeddings = list(embeddings)
        self.delete_calls: list[uuid.UUID] = []

    def list_for_session(self, session_id: uuid.UUID) -> list[FaceEmbedding]:
        return [e for e in self._embeddings if e.session_id == session_id]

    def delete_for_session(self, session_id: uuid.UUID) -> int:
        self.delete_calls.append(session_id)
        before = len(self._embeddings)
        self._embeddings = [e for e in self._embeddings if e.session_id != session_id]
        return before - len(self._embeddings)


class FakeS3Client:
    def __init__(self) -> None:
        self.deleted_objects: list[tuple[str, str]] = []

    def delete_object(self, *, Bucket: str, Key: str) -> dict:  # noqa: N803 - mirrors boto3's signature
        self.deleted_objects.append((Bucket, Key))
        return {}


def _user(user_id: uuid.UUID, full_name: str = "Real Person") -> User:
    now = datetime.now(UTC)
    return User(
        id=user_id,
        external_ref=f"EMP-{uuid.uuid4().hex[:6]}",
        full_name=full_name,
        status=UserStatus.OFFBOARDED,
        created_at=now,
        updated_at=now,
    )


def _media(session_id: uuid.UUID) -> MediaObject:
    now = datetime.now(UTC)
    return MediaObject(
        id=uuid.uuid4(),
        session_id=session_id,
        kind=MediaKind.PHOTO,
        s3_bucket="test-bucket",
        s3_key=f"enrollment/{session_id}/photo_1.jpg",
        checksum="a" * 64,
        size=1024,
        content_type="image/jpeg",
        status=MediaObjectStatus.FINALIZED,
        created_at=now,
    )


def _embedding(session_id: uuid.UUID, user_id: uuid.UUID) -> FaceEmbedding:
    return FaceEmbedding(
        id=uuid.uuid4(),
        user_id=user_id,
        session_id=session_id,
        model_version="v1",
        pose_bucket="12",
        vector=[0.0] * 512,
        created_at=datetime.now(UTC),
    )


def test_revoke_cleanup_deletes_embeddings_media_and_tombstones_user() -> None:
    session = _session(EnrollmentState.REVOKED)
    user = _user(session.user_id)
    media = [_media(session.id), _media(session.id)]
    embeddings = [_embedding(session.id, session.user_id)]

    enrollment_repo = FakeEnrollmentRepo(session)
    user_repo = FakeUserRepo(user)
    media_repo = FakeMediaRepo(media)
    embedding_repo = FakeEmbeddingRepo(embeddings)
    audit_repo = FakeAuditRepo()
    s3_client = FakeS3Client()

    outcome = worker_tasks._revoke_enrollment_cleanup_core(
        enrollment_repo, user_repo, media_repo, embedding_repo, audit_repo, s3_client, session.id
    )

    assert outcome == "executed"
    assert embedding_repo.delete_calls == [session.id]
    assert len(media_repo.deleted) == 2
    assert len(s3_client.deleted_objects) == 2
    assert user.full_name == worker_tasks.TOMBSTONE_FULL_NAME
    assert user_repo.update_calls == [user]

    completed = [
        e for e in audit_repo.entries if e["action"] == worker_tasks.REVOKE_COMPLETED_ACTION
    ]
    assert len(completed) == 1
    assert completed[0]["payload"] == {"embeddings_deleted": 1, "media_deleted": 2}


def test_revoke_cleanup_is_idempotent_on_second_call() -> None:
    session = _session(EnrollmentState.REVOKED)
    user = _user(session.user_id)
    media = [_media(session.id)]
    embeddings = [_embedding(session.id, session.user_id)]

    enrollment_repo = FakeEnrollmentRepo(session)
    user_repo = FakeUserRepo(user)
    media_repo = FakeMediaRepo(media)
    embedding_repo = FakeEmbeddingRepo(embeddings)
    audit_repo = FakeAuditRepo()
    s3_client = FakeS3Client()

    first = worker_tasks._revoke_enrollment_cleanup_core(
        enrollment_repo, user_repo, media_repo, embedding_repo, audit_repo, s3_client, session.id
    )
    second = worker_tasks._revoke_enrollment_cleanup_core(
        enrollment_repo, user_repo, media_repo, embedding_repo, audit_repo, s3_client, session.id
    )

    assert first == "executed"
    assert second == "executed"  # no-op, not an error
    # Second run found nothing left to delete and the user already tombstoned.
    completed = [
        e for e in audit_repo.entries if e["action"] == worker_tasks.REVOKE_COMPLETED_ACTION
    ]
    assert len(completed) == 2
    assert completed[1]["payload"] == {"embeddings_deleted": 0, "media_deleted": 0}
    # user.update was only called once (first run) — second run saw it was
    # already tombstoned and skipped the redundant write.
    assert user_repo.update_calls == [user]


@pytest.mark.parametrize(
    "state",
    [
        EnrollmentState.ENROLLED,
        EnrollmentState.CREATED,
        EnrollmentState.CANCELLED,
        EnrollmentState.QC_RUNNING,
    ],
)
def test_revoke_cleanup_skips_when_session_not_revoked(state: EnrollmentState) -> None:
    session = _session(state)
    user = _user(session.user_id)
    media = [_media(session.id)]
    embeddings = [_embedding(session.id, session.user_id)]

    enrollment_repo = FakeEnrollmentRepo(session)
    user_repo = FakeUserRepo(user)
    media_repo = FakeMediaRepo(media)
    embedding_repo = FakeEmbeddingRepo(embeddings)
    audit_repo = FakeAuditRepo()
    s3_client = FakeS3Client()

    outcome = worker_tasks._revoke_enrollment_cleanup_core(
        enrollment_repo, user_repo, media_repo, embedding_repo, audit_repo, s3_client, session.id
    )

    assert outcome == "skipped_not_revoked"
    assert embedding_repo.delete_calls == []
    assert media_repo.deleted == []
    assert s3_client.deleted_objects == []
    assert user.full_name != worker_tasks.TOMBSTONE_FULL_NAME
    skipped = [
        e for e in audit_repo.entries if e["action"] == worker_tasks.REVOKE_CLEANUP_SKIPPED_ACTION
    ]
    assert len(skipped) == 1
    assert skipped[0]["payload"]["reason"] == "not_revoked"


def test_revoke_cleanup_skips_when_session_not_found() -> None:
    enrollment_repo = FakeEnrollmentRepo(None)
    user_repo = FakeUserRepo(None)
    media_repo = FakeMediaRepo([])
    embedding_repo = FakeEmbeddingRepo([])
    audit_repo = FakeAuditRepo()
    s3_client = FakeS3Client()
    missing_id = uuid.uuid4()

    outcome = worker_tasks._revoke_enrollment_cleanup_core(
        enrollment_repo, user_repo, media_repo, embedding_repo, audit_repo, s3_client, missing_id
    )

    assert outcome == "skipped_not_found"
    assert audit_repo.entries[0]["payload"]["reason"] == "session_not_found"


def test_revoke_enrollment_cleanup_has_expected_retry_config() -> None:
    task = celery_app.tasks["app.worker.tasks.revoke_enrollment_cleanup"]
    assert task.autoretry_for == worker_tasks.RETRYABLE_EXCEPTIONS
    assert task.retry_backoff is True
    assert task.max_retries == 5
    assert issubclass(task.__class__, worker_tasks.DeadLetterTask)


def test_revoke_enrollment_cleanup_dead_letters_after_retries_exhausted(
    monkeypatch, eager_celery
) -> None:
    """Same dead-letter guarantee as run_enrollment_qc (NFR-OPS-02), proven
    against the actual `revoke_enrollment_cleanup` task this time — a
    permanent failure (e.g. Postgres/S3 down for good) must not silently
    disappear."""
    audit_sink: list = []
    monkeypatch.setattr(
        worker_tasks, "get_sessionmaker", lambda: lambda: _FakeDbSession(audit_sink)
    )

    def _boom(*args, **kwargs):
        raise ConnectionError("simulated permanent DB/S3 outage")

    monkeypatch.setattr(worker_tasks, "EnrollmentSessionRepository", _boom)
    monkeypatch.setattr(worker_tasks.celery_app.tasks[
        "app.worker.tasks.revoke_enrollment_cleanup"
    ], "max_retries", 1)

    result = worker_tasks.revoke_enrollment_cleanup.apply(args=[str(uuid.uuid4())])

    assert result.state == "FAILURE"
    dead_letters = [e for e in audit_sink if e.action == worker_tasks.DEAD_LETTER_ACTION]
    assert len(dead_letters) == 1
    assert dead_letters[0].payload["task"] == "app.worker.tasks.revoke_enrollment_cleanup"
    assert dead_letters[0].payload["exception_type"] == "ConnectionError"


# --- retention automation (BE-14) — Celery Beat schedule + task wiring -----


def test_beat_schedule_registers_both_retention_jobs() -> None:
    schedule = celery_app.conf.beat_schedule
    assert "backfill-retention-expiry" in schedule
    assert "purge-expired-media" in schedule
    assert (
        schedule["backfill-retention-expiry"]["task"]
        == "app.worker.tasks.backfill_retention_expiry_task"
    )
    assert (
        schedule["purge-expired-media"]["task"] == "app.worker.tasks.purge_expired_media_task"
    )
    # Both intervals are positive numbers of seconds (config-able, not zero).
    assert schedule["backfill-retention-expiry"]["schedule"] > 0
    assert schedule["purge-expired-media"]["schedule"] > 0


def test_backfill_retention_expiry_task_is_registered_and_dead_letter_based() -> None:
    task = celery_app.tasks["app.worker.tasks.backfill_retention_expiry_task"]
    assert issubclass(task.__class__, worker_tasks.DeadLetterTask)
    assert task.name == worker_tasks.backfill_retention_expiry_task.name


def test_purge_expired_media_task_is_registered_and_dead_letter_based() -> None:
    task = celery_app.tasks["app.worker.tasks.purge_expired_media_task"]
    assert issubclass(task.__class__, worker_tasks.DeadLetterTask)
    assert task.name == worker_tasks.purge_expired_media_task.name


# --- reenroll-due policy (EC-BE-05, TSD-edge-cases.md A-5) — Celery Beat
# schedule + task wiring. The service function itself
# (app/services/reenroll_due_service.py) has its own thorough unit tests in
# tests/test_reenroll_due_service.py; this only proves the task is wired
# into beat/registered/dead-letter-based, same level of coverage as the two
# retention-job wiring tests directly above.


def test_beat_schedule_registers_reenroll_due_job() -> None:
    schedule = celery_app.conf.beat_schedule
    assert "reenroll-due-check" in schedule
    assert schedule["reenroll-due-check"]["task"] == "app.worker.tasks.reenroll_due_task"
    assert schedule["reenroll-due-check"]["schedule"] > 0


def test_reenroll_due_task_is_registered_and_dead_letter_based() -> None:
    task = celery_app.tasks["app.worker.tasks.reenroll_due_task"]
    assert issubclass(task.__class__, worker_tasks.DeadLetterTask)
    assert task.name == worker_tasks.reenroll_due_task.name


def test_backfill_retention_expiry_task_end_to_end(monkeypatch, eager_celery) -> None:
    """Runs the real task body (in eager mode) against monkeypatched repos to
    prove the task wires settings + repos into retention_service correctly,
    without needing a live Postgres."""
    session = _session(EnrollmentState.ENROLLED)
    media = MediaObject(
        id=uuid.uuid4(),
        session_id=session.id,
        kind=MediaKind.PHOTO,
        s3_bucket="test-bucket",
        s3_key="photo.jpg",
        checksum="a" * 64,
        size=1024,
        content_type="image/jpeg",
        status=MediaObjectStatus.FINALIZED,
        created_at=datetime.now(UTC),
    )

    class _FakeMediaRepo:
        def __init__(self, items):
            self._items = items
            self.updated = []

        def list_finalized_without_retention(self, *, kinds):
            return [m for m in self._items if m.kind in kinds and m.retention_expires_at is None]

        def update(self, m):
            self.updated.append(m)
            return m

    media_repo = _FakeMediaRepo([media])
    enrollment_repo = FakeEnrollmentRepo(session)

    monkeypatch.setattr(
        worker_tasks, "get_sessionmaker", lambda: lambda: _FakeDbSession([])
    )
    monkeypatch.setattr(worker_tasks, "MediaObjectRepository", lambda db: media_repo)
    monkeypatch.setattr(worker_tasks, "EnrollmentSessionRepository", lambda db: enrollment_repo)

    result = worker_tasks.backfill_retention_expiry_task.apply()

    assert result.state == "SUCCESS"
    assert result.result["raw_media_set"] == 1
    assert media.retention_expires_at is not None
    assert len(media_repo.updated) == 1
