"""QC job enqueue — wired to Celery (BE-07).

Was a documented no-op integration seam for BE-06 (see git history for the
original docstring). BE-07 built the actual worker (`app/worker/`), so this
now dispatches the real `run_enrollment_qc` task.

Dispatch is deliberately **best-effort**: `POST /enrollments/{id}/complete`
(BE-06) has already committed the session's `CAPTURED -> QC_RUNNING`
transition and the `enrollment.media_completed` audit entry by the time this
is called — those are the source of truth, not the Celery dispatch. If the
broker (Redis) is down or unreachable, `enqueue_qc_job` swallows the error,
logs it, and returns normally so `/complete` still responds 200. The QC job
itself will simply not run yet; retry-of-dispatch (not just retry-of-job) is
a known gap, tracked as a manual/ops step (re-run `enqueue_qc_job` for
sessions stuck in QC_RUNNING) rather than solved here — see backend/README.md.
"""

import logging
import uuid

logger = logging.getLogger(__name__)


def enqueue_qc_job(session_id: uuid.UUID) -> None:
    """Enqueue an async quality-check job for `session_id` (FR-ENR-06).

    Never raises: broker/connection errors are caught and logged so the
    caller (the `/complete` endpoint's critical DB transaction) is never
    affected by Redis/Celery availability.
    """
    try:
        from app.worker.tasks import run_enrollment_qc

        run_enrollment_qc.delay(str(session_id))
    except Exception:
        logger.exception(
            "qc_queue.enqueue_qc_job: failed to dispatch run_enrollment_qc for "
            "session_id=%s (broker unavailable?) — session remains QC_RUNNING "
            "until the job is (re)dispatched",
            session_id,
        )
