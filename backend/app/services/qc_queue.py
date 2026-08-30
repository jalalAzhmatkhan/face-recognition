"""QC job enqueue — INTEGRATION SEAM for BE-07 (Celery worker infra).

BE-07 (the actual Celery app/worker that consumes quality-check jobs) does
not exist yet. Building it is explicitly out of scope for BE-06 — this
module exists solely so `POST /enrollments/{id}/complete` (BE-06) has ONE
clearly-named call site to enqueue the async QC job (FR-ENR-06) against,
instead of either blocking on media/S3 access work that doesn't belong in
this task, or leaving no hook at all for BE-07 to wire into later.

For now `enqueue_qc_job` is a documented no-op: it logs at INFO level and
returns immediately. When BE-07 lands, this function's body should be
replaced with the real Celery `.delay()`/`.apply_async()` call (or whatever
queue technology BE-07 chooses) — callers (app/routers/enrollments.py) do
not need to change.
"""

import logging
import uuid

logger = logging.getLogger(__name__)


def enqueue_qc_job(session_id: uuid.UUID) -> None:
    """Enqueue an async quality-check job for `session_id` (FR-ENR-06).

    NO-OP TODAY (BE-07 not implemented yet): logs the intent and returns.
    Does not raise, does not block, does not talk to a real queue/broker.
    """
    logger.info(
        "qc_queue.enqueue_qc_job: no-op (BE-07 Celery worker infra not yet "
        "implemented) session_id=%s",
        session_id,
    )
