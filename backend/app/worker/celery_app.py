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
