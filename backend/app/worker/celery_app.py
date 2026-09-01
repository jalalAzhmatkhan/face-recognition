"""Celery application instance (BE-07, NFR-OPS-02: async/retryable jobs).

Broker and result backend both reuse `Settings.redis_url` (already wired in
XC-02/`app/core/config.py`) — there is deliberately no separate
`CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND` env var, to avoid two sources of
truth for "where is Redis".

Import-time safety: constructing `Celery(...)` never opens a network
connection by itself (broker/backend URLs are only dialed lazily, on the
first `.delay()`/worker start/result fetch) — so importing this module (and
therefore `app.worker.tasks`, and therefore `app.services.qc_queue`) stays
safe even when Redis is unreachable or `REDIS_URL` is unset (falls back to
the same `redis://localhost:6379/0` default used by `docker-compose.dev.yml`
so local `uv run celery ...` "just works" without a `.env`).
"""

from celery import Celery

from app.core.config import get_settings

_DEFAULT_DEV_REDIS_URL = "redis://localhost:6379/0"

# --- Celery Beat (BE-14) -----------------------------------------------
# This is the FIRST task to add a Celery Beat schedule to this project —
# every task before BE-07/BE-08/BE-09 was on-demand only (`.delay(...)`
# dispatched from a request handler). Beat entries below are inert unless a
# SEPARATE `celery beat` process is actually running:
#
#   uv run celery -A app.worker.celery_app beat --loglevel=info
#
# This is a DIFFERENT process from `celery -A app.worker.celery_app worker
# --loglevel=info` (see backend/README.md "Running the worker") — beat only
# enqueues jobs on schedule, it does not execute them; you still need at
# least one worker running to actually process what beat enqueues. Forgetting
# to start beat is exactly how a schedule becomes silent dead code, so this
# is called out again in backend/README.md under "Retention automation".


def _redis_url() -> str:
    settings = get_settings()
    return settings.redis_url or _DEFAULT_DEV_REDIS_URL


celery_app = Celery(
    "frac_backend",
    broker=_redis_url(),
    backend=_redis_url(),
    include=["app.worker.tasks"],
)

# Job semantics per NFR-OPS-02 (FSD-AI.md): training/enrollment-processing
# jobs are async and retryable — idempotent jobs, dead-letter handling.
celery_app.conf.update(
    task_acks_late=True,  # redeliver to another worker if this one dies mid-task
    worker_prefetch_multiplier=1,  # don't hoard jobs behind a slow one (pairs with acks_late)
    task_reject_on_worker_lost=True,  # worker killed mid-task -> requeue, not silently dropped
    task_default_queue="frac_default",
    result_expires=60 * 60 * 24,  # 1 day; results aren't the source of truth (audit_logs is)
    timezone="UTC",
    enable_utc=True,
)

_settings = get_settings()

# BE-14 retention automation: two scheduled jobs, both defined as regular
# tasks in app/worker/tasks.py (`backfill_retention_expiry_task` /
# `purge_expired_media_task`) so they share the same DeadLetterTask
# retry/idempotency/audit infra as every on-demand task in this module.
celery_app.conf.beat_schedule = {
    "backfill-retention-expiry": {
        "task": "app.worker.tasks.backfill_retention_expiry_task",
        "schedule": _settings.retention_backfill_interval_seconds,
    },
    "purge-expired-media": {
        "task": "app.worker.tasks.purge_expired_media_task",
        "schedule": _settings.retention_purge_interval_seconds,
    },
    # EC-BE-05 (TSD-edge-cases.md A-5): re-enrollment-due policy. Daily by
    # default (see Settings.reenroll_due_check_interval_seconds) — a
    # slow-moving policy signal, not a hot path.
    "reenroll-due-check": {
        "task": "app.worker.tasks.reenroll_due_task",
        "schedule": _settings.reenroll_due_check_interval_seconds,
    },
}
