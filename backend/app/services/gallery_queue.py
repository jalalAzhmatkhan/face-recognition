"""Gallery re-embedding job enqueue (TR-08, FR-TRN-06).

Mirrors `app/services/training_queue.py` exactly: best-effort dispatch
against the shared Redis broker (`app/worker/celery_app.py`). Called from
`app/services/training_service.py::promote_model` right after a promotion
has already committed — a broker outage here must never undo or fail an
already-successful promotion; the gallery simply doesn't get re-embedded
until this is (re)dispatched, same documented manual-retry gap as the
QC/revocation/training-evaluation queues.

The actual re-embedding logic (`ai_training.worker.tasks.run_gallery_reembed_job_core`)
runs entirely in ai-training's own Celery worker, registered under the
identical task name — see `app/worker/tasks.py`'s `run_gallery_reembed_job`
docstring for why backend's own copy of that task name must never execute.
"""

import logging

logger = logging.getLogger(__name__)


def enqueue_gallery_reembed(model_version: str) -> None:
    """Enqueue the async gallery re-embedding job for `model_version`
    (FR-TRN-06). Never raises: broker/connection errors are caught and
    logged so a Redis outage never turns a successful promotion HTTP
    response into a 500."""
    try:
        from app.worker.tasks import run_gallery_reembed_job

        run_gallery_reembed_job.delay(model_version=model_version)
    except Exception:
        logger.exception(
            "gallery_queue.enqueue_gallery_reembed: failed to dispatch "
            "run_gallery_reembed_job for model_version=%s (broker unavailable?) — "
            "gallery embeddings remain un-re-embedded until this is (re)dispatched",
            model_version,
        )
