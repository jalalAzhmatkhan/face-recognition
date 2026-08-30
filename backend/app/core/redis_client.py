"""Redis client factory for the policy cache (BE-10, TSD §2.2, FR-INF-05)
and the access-event live-stream pub/sub (BE-11, FR-MON-01).

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
own lazy clients. `redis.asyncio.Redis.from_url(...)` has the identical
lazy-connection guarantee (same redis-py package, `redis>=6.4.0` per
`uv.lock`, which bundles the `redis.asyncio` submodule).

BE-11 adds a SEPARATE async client (`build_async_redis_client` /
`get_async_redis_client`) rather than reusing the sync one: the SSE stream
endpoint needs `redis.asyncio.Redis().pubsub()` so subscribing/listening
never blocks the FastAPI event loop, while the existing sync client stays
exactly as-is for `policy_cache.py`'s blocking get/set/delete calls on the
request-handling hot path.
"""

from functools import lru_cache

import redis
import redis.asyncio as redis_asyncio

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


def build_async_redis_client() -> redis_asyncio.Redis:
    settings = get_settings()
    url = settings.redis_url or _DEFAULT_DEV_REDIS_URL
    return redis_asyncio.Redis.from_url(url, decode_responses=True)


@lru_cache
def get_async_redis_client() -> redis_asyncio.Redis:
    """Process-wide cached ASYNC client for the SSE live-stream endpoint
    (`GET /stream/access-events`, BE-11). Kept separate from
    `get_redis_client()` — see module docstring. Tests override this
    dependency with an in-memory fake `pubsub()` (no real Redis instance in
    the test environment, same as `get_redis_client()`)."""
    return build_async_redis_client()
