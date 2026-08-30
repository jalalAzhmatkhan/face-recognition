"""Celery application instance for the ai-training worker (TR-02/TR-03).

`ai-training` is a separate Python project from `backend/` (own
venv/pyproject/lockfile) and cannot import `backend/app/worker/celery_app.py`.
The two projects must nonetheless cooperate on ONE logical job queue:

- `backend/app/services/qc_queue.py` dispatches
  `run_enrollment_qc.delay(session_id)` by NAME
  (`"app.worker.tasks.run_enrollment_qc"`) against a shared Redis broker.
- Celery routes a `.delay()` call purely by task name + queue, not by which
  codebase defines it. So THIS module builds a second, independent Celery
  app pointed at the SAME Redis instance, and `ai_training.worker.tasks`
  registers its real implementation under that EXACT SAME name
  (`celery_app.task(name="app.worker.tasks.run_enrollment_qc", ...)`).
  Whichever worker process is actually running and subscribed to the queue
  picks up and executes the job — that worker is now this one, not
  backend's BE-07 stub.

Operational implications (see ai-training/README.md "Menjalankan worker"):
- `TRN_REDIS_URL` (this project) MUST be set to the SAME value as
  backend's `REDIS_URL` — there is no automatic sharing between the two
  separate config systems/env namespaces.
- `task_default_queue` below MUST match backend's `"frac_default"`
  (`backend/app/worker/celery_app.py`) so dispatches actually reach a
  worker consuming from this queue.
- Run EITHER backend's worker OR this one against a given environment for
  `run_enrollment_qc` — not both — otherwise whichever process happens to
  grab a given job wins non-deterministically (backend's stub explicitly
  must not run once this one is deployed; see backend/app/worker/tasks.py's
  `_run_enrollment_qc_stub` docstring, "TR-02 replaces the body of this
  function").
"""

from celery import Celery

from ai_training.config import get_settings

_DEFAULT_DEV_REDIS_URL = "redis://localhost:6379/0"


def _redis_url() -> str:
    settings = get_settings()
    return settings.redis_url or _DEFAULT_DEV_REDIS_URL


celery_app = Celery(
    "ai_training_worker",
    broker=_redis_url(),
    backend=_redis_url(),
    include=["ai_training.worker.tasks"],
)

celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    # MUST match backend/app/worker/celery_app.py's task_default_queue —
    # this is the queue backend's qc_queue.py dispatches into.
    task_default_queue="frac_default",
    result_expires=60 * 60 * 24,
    timezone="UTC",
    enable_utc=True,
)
