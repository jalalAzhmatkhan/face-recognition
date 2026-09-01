"""Training-evaluation job enqueue (BE-13).

Mirrors `app/services/qc_queue.py` / `app/services/revocation_queue.py`
exactly: best-effort dispatch against the shared Redis broker
(`app/worker/celery_app.py`). `POST /api/v1/training/jobs` has already
committed the `training_jobs` row (status=PENDING) by the time this is
called, so a broker outage here never fails the endpoint — the job simply
stays PENDING until (re)dispatched, same documented manual-retry gap as the
QC/revocation queues (see backend/README.md).

The actual evaluation logic (`ai_training.evaluation.metrics.evaluate_candidate`)
runs entirely in ai-training's own Celery worker
(`ai_training/worker/tasks.py::run_training_evaluation_job`), registered
under the identical task name — see `app/worker/tasks.py`'s
`run_training_evaluation_job` docstring for why backend's own copy of that
task name must never actually execute.
"""

import logging
import uuid

logger = logging.getLogger(__name__)


def enqueue_training_job(job_id: uuid.UUID, model_version: str, benchmark_id: str) -> None:
    """Enqueue the async training-evaluation job for `job_id` (FR-TRN-02).

    Never raises: broker/connection errors are caught and logged so the
    caller (the `/training/jobs` endpoint's already-committed job row) is
    never affected by Redis/Celery availability.
    """
    try:
        from app.worker.tasks import run_training_evaluation_job

        run_training_evaluation_job.delay(
            job_id=str(job_id), model_version=model_version, benchmark_id=benchmark_id
        )
    except Exception:
        logger.exception(
            "training_queue.enqueue_training_job: failed to dispatch "
            "run_training_evaluation_job for job_id=%s (broker unavailable?) — job "
            "remains PENDING until the job is (re)dispatched",
            job_id,
        )


def enqueue_backfill_masked_templates_job(job_id: uuid.UUID) -> None:
    """Enqueue the async D-4.5 backfill job for `job_id`
    (`job_type=BACKFILL_MASKED_TEMPLATES`, EC-BE-03/this task).

    Mirrors `enqueue_training_job` exactly (same best-effort/never-raises
    dispatch against the shared Redis broker) — the actual backfill logic
    (`ai_training.embedding.synthetic_masked` reuse + per-session
    iteration) runs entirely in ai-training's own Celery worker
    (`ai_training/worker/tasks.py::run_backfill_masked_templates_job`),
    registered under the identical task name — see
    `app/worker/tasks.py`'s `run_backfill_masked_templates_job` docstring
    for why backend's own copy of that task name must never actually
    execute. Unlike `enqueue_training_job`, there is no `model_version`/
    `benchmark_id` to pass through — the backfill job takes only `job_id`
    and discovers every legacy `ENROLLED` session itself.
    """
    try:
        from app.worker.tasks import run_backfill_masked_templates_job

        run_backfill_masked_templates_job.delay(job_id=str(job_id))
    except Exception:
        logger.exception(
            "training_queue.enqueue_backfill_masked_templates_job: failed to dispatch "
            "run_backfill_masked_templates_job for job_id=%s (broker unavailable?) — job "
            "remains PENDING until the job is (re)dispatched",
            job_id,
        )
