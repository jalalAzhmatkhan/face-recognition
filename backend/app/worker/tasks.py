"""Celery tasks + shared retry/dead-letter/idempotency infra (BE-07).

NFR-OPS-02 (FSD-AI.md): "Training and enrollment-processing are async and
retryable (idempotent jobs, dead-letter handling)." This module provides the
generic infra two ways:

1. **Retry with exponential backoff** — every task declared with
   `DeadLetterTask` as its `base` and Celery's own `autoretry_for=(...)`,
   `retry_backoff=True`, `max_retries=...` kwargs (see `run_enrollment_qc`
   below for the canonical example). This is stock Celery behaviour, not
   reimplemented here.

2. **Dead-letter handling, observable via `audit_logs`** — this system
   already has one append-only audit trail (`audit_logs`, BE-04,
   NFR-SEC-05) and no separate DLQ table/queue. Rather than stand up a
   second persistence mechanism, `DeadLetterTask.on_failure` (a Celery hook
   that fires once a task fails *for real* — for an `autoretry_for` task,
   that means retries are exhausted) writes one `audit_logs` row with
   `action="job.dead_letter"`. Query it directly:

       SELECT * FROM audit_logs
       WHERE action = 'job.dead_letter'
       ORDER BY at DESC;

   `payload` carries `{task, task_id, args, kwargs, exception_type,
   exception_message}` for triage. See backend/README.md for the full
   runbook (how to trigger + observe this against a real Redis+Postgres).

**Idempotency** follows the state-machine-driven pattern used throughout
this codebase (see app/services/enrollment_state_machine.py) instead of a
separate idempotency-key table: a job checks the *current* state of the
resource it references before doing any work, and no-ops (with an audit log
entry, not silently) if that resource has already moved past the state the
job expects. A duplicate delivery of the same job message is therefore safe
to run twice — the second run observes the state left by the first and
does nothing.
"""

import logging
import uuid
from typing import Any

from celery import Task

from app.core.aws import get_s3_client
from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.models.enums import EnrollmentState
from app.repositories.audit_logs import AuditLogRepository
from app.repositories.enrollments import EnrollmentSessionRepository
from app.repositories.face_embeddings import FaceEmbeddingRepository
from app.repositories.media_objects import MediaObjectRepository
from app.repositories.users import UserRepository
from app.services import retention_service
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)

# Exceptions that are worth retrying (transient: DB hiccup, S3 blip, etc.).
# Kept broad-but-named (not bare `Exception`) so a genuine programming bug
# still surfaces quickly in CI/tests rather than silently retrying 5x.
RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
)

DEAD_LETTER_ACTION = "job.dead_letter"


class DeadLetterTask(Task):
    """Base class for every worker task: adds dead-letter audit logging.

    Usage (see `run_enrollment_qc`):

        @celery_app.task(
            base=DeadLetterTask,
            bind=True,
            autoretry_for=RETRYABLE_EXCEPTIONS,
            retry_backoff=True,
            retry_backoff_max=600,
            retry_jitter=True,
            max_retries=5,
        )
        def my_task(self, ...): ...

    Celery invokes `on_failure` exactly when a task fails *permanently* —
    for an `autoretry_for` task that's after `max_retries` is exhausted
    (in-flight retries raise `Retry`, not a failure, so they do NOT trigger
    this). That makes `on_failure` the correct, single choke point for
    dead-letter handling regardless of which concrete task failed.

    Deliberately opens its own DB session (rather than assuming the task
    body's session is still valid/open) — a permanent failure may itself be
    a DB error, so the dead-letter write must not depend on the session
    that just broke.
    """

    def on_failure(
        self,
        exc: BaseException,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: Any,
    ) -> None:
        super().on_failure(exc, task_id, args, kwargs, einfo)
        try:
            session_factory = get_sessionmaker()
            db = session_factory()
            try:
                AuditLogRepository(db).record(
                    actor="system:celery-worker",
                    action=DEAD_LETTER_ACTION,
                    entity=f"task:{self.name}:{task_id}",
                    payload={
                        "task": self.name,
                        "task_id": task_id,
                        "args": [str(a) for a in args],
                        "kwargs": {k: str(v) for k, v in kwargs.items()},
                        "exception_type": type(exc).__name__,
                        "exception_message": str(exc),
                    },
                )
            finally:
                db.close()
        except Exception:  # noqa: BLE001 - dead-letter logging must never raise
            logger.exception(
                "worker.dead_letter_write_failed task=%s task_id=%s", self.name, task_id
            )


def _run_enrollment_qc_stub(
    enrollment_repo: EnrollmentSessionRepository,
    audit_repo: AuditLogRepository,
    session_id: uuid.UUID,
) -> str:
    """Core logic of the QC stub, factored out for unit testing without a
    Celery task context (no `self`, no broker, no DB session lifecycle).

    Returns a short outcome string (`"executed"`, `"skipped_not_found"`,
    `"skipped_wrong_state"`) purely so tests can assert on it.
    """
    session = enrollment_repo.get(session_id)
    if session is None:
        logger.warning("run_enrollment_qc: session %s not found, skipping", session_id)
        audit_repo.record(
            actor="system:celery-worker",
            action="job.qc_stub_skipped",
            entity=f"enrollment_session:{session_id}",
            payload={"reason": "session_not_found"},
        )
        return "skipped_not_found"

    if session.state != EnrollmentState.QC_RUNNING:
        # Idempotency (NFR-OPS-02): a duplicate delivery of this job after
        # the session has already moved on (QC_PASSED / REJECTED_QUALITY /
        # CANCELLED / ...) is a no-op, not an error. This is what makes
        # `run_enrollment_qc.delay(...)` safe to call more than once for the
        # same session_id.
        logger.info(
            "run_enrollment_qc: session %s is %s (not QC_RUNNING), skipping duplicate job",
            session_id,
            session.state,
        )
        audit_repo.record(
            actor="system:celery-worker",
            action="job.qc_stub_skipped",
            entity=f"enrollment_session:{session_id}",
            payload={"reason": "not_qc_running", "state": session.state.value},
        )
        return "skipped_wrong_state"

    # --- STUB ONLY (BE-07 scope) ---------------------------------------
    # This is explicitly NOT the real QC pipeline. It does not run face
    # detection, does not compute pose coverage/sharpness/exposure, and it
    # MUST NOT transition the session to QC_PASSED or REJECTED_QUALITY —
    # that is an AI-model decision, owned by TR-02 (ai-engineer,
    # ai-training/), not backend infra. BE-07's job is only to prove the
    # worker plumbing (dispatch, retry, idempotency, dead-letter) works.
    #
    # TR-02 replaces the body of this function (not `run_enrollment_qc`'s
    # name/signature/decorator config) with the real pipeline, ending with
    # a call to `enrollment_service.transition_session(...)` to
    # QC_PASSED/REJECTED_QUALITY. `app/services/qc_queue.py` does not need
    # to change when that happens.
    audit_repo.record(
        actor="system:celery-worker",
        action="job.qc_stub_executed",
        entity=f"enrollment_session:{session_id}",
        payload={
            "session_id": str(session_id),
            "note": "real QC pipeline: TR-02 (ai-training/) — this is a BE-07 infra stub",
        },
    )
    return "executed"


@celery_app.task(
    name="app.worker.tasks.run_enrollment_qc",
    base=DeadLetterTask,
    bind=True,
    autoretry_for=RETRYABLE_EXCEPTIONS,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
)
def run_enrollment_qc(self: Task, session_id: str) -> str:
    """Async quality-check job for an enrollment session (FR-ENR-06).

    STUB for BE-07 — see module docstring and `_run_enrollment_qc_stub`.
    Real QC pipeline lands in TR-02 without changing this task's name or
    signature (`app/services/qc_queue.py` calls
    `run_enrollment_qc.delay(str(session_id))` and never needs to change).
    """
    session_factory = get_sessionmaker()
    db = session_factory()
    try:
        enrollment_repo = EnrollmentSessionRepository(db)
        audit_repo = AuditLogRepository(db)
        return _run_enrollment_qc_stub(enrollment_repo, audit_repo, uuid.UUID(session_id))
    finally:
        db.close()


# --- revoke_enrollment_cleanup (BE-08, FR-ENR-09/NFR-SEC-03/ASM-12) --------

# What "tombstoning" a user means here: the row is never hard-deleted (many
# FKs — devices/access_events/audit_logs/etc. — reference `users.id`, and
# hard-delete would either violate referential integrity or, worse, cascade
# and silently destroy unrelated audit history). Instead only the one
# column that identifies a *person* (`full_name`) is redacted; `external_ref`
# (the business key audit/reporting joins against) is deliberately left
# untouched per BE-08 instructions.
TOMBSTONE_FULL_NAME = "[REVOKED]"

REVOKE_CLEANUP_SKIPPED_ACTION = "job.revoke_cleanup_skipped"
REVOKE_COMPLETED_ACTION = "enrollment.revoke_completed"


def _revoke_enrollment_cleanup_core(
    enrollment_repo: EnrollmentSessionRepository,
    user_repo: UserRepository,
    media_repo: MediaObjectRepository,
    embedding_repo: FaceEmbeddingRepository,
    audit_repo: AuditLogRepository,
    s3_client: Any,
    session_id: uuid.UUID,
) -> str:
    """Core logic of the revocation cleanup job, factored out for unit
    testing without a Celery task context (same split as
    `_run_enrollment_qc_stub` above).

    Returns a short outcome string (`"executed"`, `"skipped_not_found"`,
    `"skipped_not_revoked"`) purely so tests can assert on it.

    Idempotency (NFR-OPS-02): a duplicate delivery of this job — including
    the case where a previous run already completed it — is safe. Deleting
    already-deleted `face_embeddings`/`media_objects` rows is a no-op
    (`DELETE ... WHERE` matching 0 rows is not an error), an already-absent
    S3 object is a no-op delete by S3/MinIO semantics, and an already
    `TOMBSTONE_FULL_NAME` user is left untouched rather than re-written. The
    job still records a fresh `enrollment.revoke_completed` audit entry each
    time it runs (with counts reflecting however much work was actually
    left to do, including 0), rather than treating a repeat run as an error.
    """
    session = enrollment_repo.get(session_id)
    if session is None:
        logger.warning("revoke_enrollment_cleanup: session %s not found, skipping", session_id)
        audit_repo.record(
            actor="system:celery-worker",
            action=REVOKE_CLEANUP_SKIPPED_ACTION,
            entity=f"enrollment_session:{session_id}",
            payload={"reason": "session_not_found"},
        )
        return "skipped_not_found"

    if session.state != EnrollmentState.REVOKED:
        # Guards against ever wiping embeddings/media for a session that
        # was never actually revoked (e.g. a malformed/duplicate dispatch
        # racing an in-flight revoke, or a stale job replayed against a
        # session id that has since been reused/miscopied).
        logger.warning(
            "revoke_enrollment_cleanup: session %s is %s (not REVOKED), skipping",
            session_id,
            session.state,
        )
        audit_repo.record(
            actor="system:celery-worker",
            action=REVOKE_CLEANUP_SKIPPED_ACTION,
            entity=f"enrollment_session:{session_id}",
            payload={"reason": "not_revoked", "state": session.state.value},
        )
        return "skipped_not_revoked"

    embeddings_deleted = embedding_repo.delete_for_session(session_id)

    media_deleted = 0
    for media in media_repo.list_for_session(session_id):
        # S3/MinIO DeleteObject is idempotent by nature (deleting an
        # already-absent key succeeds rather than erroring), so this is
        # safe to run again on a retry/duplicate delivery.
        s3_client.delete_object(Bucket=media.s3_bucket, Key=media.s3_key)
        media_repo.delete(media)
        media_deleted += 1

    user = user_repo.get(session.user_id)
    if user is not None and user.full_name != TOMBSTONE_FULL_NAME:
        user.full_name = TOMBSTONE_FULL_NAME
        user_repo.update(user)

    audit_repo.record(
        actor="system:celery-worker",
        action=REVOKE_COMPLETED_ACTION,
        entity=f"enrollment_session:{session_id}",
        payload={"embeddings_deleted": embeddings_deleted, "media_deleted": media_deleted},
    )
    return "executed"


@celery_app.task(
    name="app.worker.tasks.revoke_enrollment_cleanup",
    base=DeadLetterTask,
    bind=True,
    autoretry_for=RETRYABLE_EXCEPTIONS,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
)
def revoke_enrollment_cleanup(self: Task, session_id: str) -> str:
    """Async revocation cleanup job (FR-ENR-09, NFR-SEC-03, ASM-12).

    Dispatched by `app/services/revocation_service.py` (via
    `app/services/revocation_queue.py`) right after `DELETE
    /enrollments/{id}` synchronously transitions the session to REVOKED and
    sets `user.status = OFFBOARDED`. This job performs the physical
    cleanup within the FR-ENR-09/ASM-12 24h SLA: hard-deletes every
    `face_embeddings` row for the session, deletes every associated S3
    object + its `media_objects` row, and tombstones the user's
    `full_name` (see `TOMBSTONE_FULL_NAME` above). See
    `_revoke_enrollment_cleanup_core` for the idempotency argument.
    """
    session_factory = get_sessionmaker()
    db = session_factory()
    try:
        enrollment_repo = EnrollmentSessionRepository(db)
        user_repo = UserRepository(db)
        media_repo = MediaObjectRepository(db)
        embedding_repo = FaceEmbeddingRepository(db)
        audit_repo = AuditLogRepository(db)
        s3_client = get_s3_client()
        return _revoke_enrollment_cleanup_core(
            enrollment_repo,
            user_repo,
            media_repo,
            embedding_repo,
            audit_repo,
            s3_client,
            uuid.UUID(session_id),
        )
    finally:
        db.close()


# --- Retention automation (BE-14, ASM-10, NFR-SEC-03) ----------------------
#
# Two scheduled jobs (see app/worker/celery_app.py's `beat_schedule`) that
# wrap app/services/retention_service.py — that module has the full design
# rationale (anchor timestamps, idempotency, why a per-item failure doesn't
# sink the batch). These tasks are thin wrappers, same shape as every other
# task in this file: open a DB session, build repos, call the core service
# function, close the session.
#
# Deliberately NOT using `autoretry_for`/`DeadLetterTask`'s retry machinery
# here the way `run_enrollment_qc`/`revoke_enrollment_cleanup` do: both
# retention jobs are periodic (beat re-dispatches them every interval
# regardless), and both are already internally retry-safe per-item (a
# transient S3/DB blip on one media row is caught, logged, and picked up
# again on the *next* scheduled run rather than needing Celery-level retry
# of the whole batch). They still use `DeadLetterTask` as their base so a
# task-level catastrophic failure (e.g. the DB is down for the whole run)
# is still recorded in `audit_logs` the same way as every other task's
# dead-letter path.


@celery_app.task(
    name="app.worker.tasks.backfill_retention_expiry_task",
    base=DeadLetterTask,
    bind=True,
)
def backfill_retention_expiry_task(self: Task) -> dict[str, int]:
    """Scheduled job (hourly by default): set `retention_expires_at` on any
    FINALIZED media that doesn't have it yet. See
    `retention_service.backfill_retention_expiry` for the full logic."""
    settings = get_settings()
    session_factory = get_sessionmaker()
    db = session_factory()
    try:
        media_repo = MediaObjectRepository(db)
        enrollment_repo = EnrollmentSessionRepository(db)
        result = retention_service.backfill_retention_expiry(
            media_repo,
            enrollment_repo,
            raw_media_days=settings.retention_raw_media_days,
            event_frame_days=settings.retention_event_frame_days,
        )
        return {
            "raw_media_set": result.raw_media_set,
            "event_frame_set": result.event_frame_set,
            "skipped_not_enrolled": result.skipped_not_enrolled,
        }
    finally:
        db.close()


@celery_app.task(
    name="app.worker.tasks.purge_expired_media_task",
    base=DeadLetterTask,
    bind=True,
)
def purge_expired_media_task(self: Task) -> dict[str, int]:
    """Scheduled job (every few hours by default): hard-delete every
    `media_objects` row (+ its S3 object) whose `retention_expires_at` has
    passed, auditing each deletion. See
    `retention_service.purge_expired_media` for the full logic."""
    session_factory = get_sessionmaker()
    db = session_factory()
    try:
        media_repo = MediaObjectRepository(db)
        audit_repo = AuditLogRepository(db)
        s3_client = get_s3_client()
        result = retention_service.purge_expired_media(media_repo, audit_repo, s3_client)
        return {"purged": result.purged, "failed": result.failed}
    finally:
        db.close()
