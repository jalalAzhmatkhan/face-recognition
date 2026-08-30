"""Redis client factory for the policy cache (BE-10, TSD §2.2, FR-INF-05).

Mirrors `app/worker/celery_app.py`'s `_redis_url()` fallback so `uv run`
works locally without a `.env`: reuses `Settings.redis_url`, falling back to
`redis://localhost:6379/0` when unset — deliberately the SAME default value
as celery_app.py (single source of truth for "where is Redis" stays
`Settings.redis_url`; the fallback constant is duplicated here rather than
importing celery_app, so that importing this module never pulls in the
whole Celery app just to read a URL).

Import-time safety: `redis.Redis.from_url(...)` does not open a network
connection eagerly (redis-py connections are lazy, opened on the first
command) — so importing/constructing this client stays safe even when Redis
is unreachable or unconfigured, matching the same import-time-safety
guarantee `app/core/aws.py`/`app/worker/celery_app.py` document for their
own lazy clients.
"""

from functools import lru_cache

import redis

from app.core.config import get_settings

_DEFAULT_DEV_REDIS_URL = "redis://localhost:6379/0"


def build_redis_client() -> redis.Redis:
    settings = get_settings()
    url = settings.redis_url or _DEFAULT_DEV_REDIS_URL
    return redis.Redis.from_url(url, decode_responses=True)


@lru_cache
def get_redis_client() -> redis.Redis:
    """Process-wide cached client (mirrors `get_s3_client()`/`get_settings()`).

    FastAPI routes depend on this via `Depends(get_redis_client)`; tests
    override it with an in-memory fake exposing the small `get`/`set`/
    `delete` surface `app/services/policy_cache.py` actually uses — no real
    Redis connection is ever opened in automated tests (there is no Redis
    instance in this test environment).
    """
    return build_redis_client()
