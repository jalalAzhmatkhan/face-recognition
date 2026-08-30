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

from app.db.session import get_sessionmaker
from app.models.enums import EnrollmentState
from app.repositories.audit_logs import AuditLogRepository
from app.repositories.enrollments import EnrollmentSessionRepository
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
