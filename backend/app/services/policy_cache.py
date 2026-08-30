"""Per-user policy/status snapshot cache (BE-10, TSD §2.2, FR-INF-05).

TSD §2.2 ("Recognition at the Door"): "Policy check on the hot path uses a
Redis-cached snapshot of user status/door policy (TTL <= 30 s) so a DB
outage does not block decisions; fail-secure if cache empty."

This module is split into three deliberately narrow responsibilities:

  - `build_snapshot`  — read the DB and assemble a `PolicySnapshot`.
  - `get_cached_snapshot` — read-ONLY from Redis. Never falls back to the
    DB on a miss: a miss (expired TTL, key never written, or Redis itself
    unreachable) must surface as `None` so the *caller* can apply
    fail-secure DENY semantics (see app/services/access_event_service.py).
    Silently querying the DB here instead would defeat the whole point of
    "cache empty -> fail secure" and would also reintroduce the DB as a
    hard dependency of the hot path.
  - `refresh_cache` — query the DB and (best-effort) write the fresh
    snapshot back to Redis. Called proactively by access-policy CRUD
    (app/services/access_policy_service.py) and by the user-status-update
    endpoint (app/routers/users.py) so a policy/status change is effective
    well inside the <=30s TTL instead of waiting for passive expiry. Also
    invoked lazily (best-effort, non-blocking) by the access-event ingest
    endpoint on a cache miss, to improve the odds of a hit on the *next*
    request — never to salvage the *current* one.

v1 limitation: `access_policies.group_id` has no resolved membership source
in the current schema (no user<->group mapping table exists yet), so
`build_snapshot` only resolves policies scoped directly by `user_id`.
Group-scoped policies are silently excluded from every snapshot until a
group-membership model is introduced — a known, documented gap (see BE-10
task instructions), not a bug.
"""

import logging
import uuid
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel

from app.models.enums import UserStatus
from app.repositories.access_policies import AccessPolicyRepository
from app.repositories.users import UserRepository

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 30


class RedisLike(Protocol):
    """The minimal subset of the redis-py client surface this module uses.

    Kept as a Protocol (rather than importing `redis.Redis` directly as the
    type) so tests can hand in a trivial in-memory fake without a real Redis
    server — see backend/tests for the fake used there.
    """

    def get(self, name: str) -> str | bytes | None: ...

    def set(self, name: str, value: str, ex: int | None = None) -> object: ...

    def delete(self, name: str) -> object: ...


class PolicySnapshotEntry(BaseModel):
    door_group: str
    allowed: bool
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class PolicySnapshot(BaseModel):
    status: UserStatus
    policies: list[PolicySnapshotEntry]


def _cache_key(user_id: uuid.UUID) -> str:
    return f"policy_snapshot:{user_id}"


def build_snapshot(
    user_repo: UserRepository,
    policy_repo: AccessPolicyRepository,
    user_id: uuid.UUID,
) -> PolicySnapshot | None:
    """Assemble a fresh snapshot straight from the DB. `None` if the user
    doesn't exist (a deleted/unknown user has nothing to cache)."""
    user = user_repo.get(user_id)
    if user is None:
        return None

    policies = policy_repo.list_for_user(user_id)
    return PolicySnapshot(
        status=user.status,
        policies=[
            PolicySnapshotEntry(
                door_group=p.door_group,
                allowed=p.allowed,
                valid_from=p.valid_from,
                valid_to=p.valid_to,
            )
            for p in policies
        ],
    )


def get_cached_snapshot(redis_client: RedisLike, user_id: uuid.UUID) -> PolicySnapshot | None:
    """Pure cache read. NEVER queries the DB. Returns `None` on a miss,
    malformed cache entry, OR a Redis-level error (connection down, etc) —
    all three are indistinguishable to the caller on purpose, since the
    caller's only correct response to any of them is fail-secure DENY."""
    try:
        raw = redis_client.get(_cache_key(user_id))
    except Exception:
        logger.warning("policy_cache_read_failed", extra={"user_id": str(user_id)})
        return None

    if raw is None:
        return None

    try:
        return PolicySnapshot.model_validate_json(raw)
    except Exception:
        logger.warning("policy_cache_deserialize_failed", extra={"user_id": str(user_id)})
        return None


def refresh_cache(
    redis_client: RedisLike,
    user_repo: UserRepository,
    policy_repo: AccessPolicyRepository,
    user_id: uuid.UUID,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> PolicySnapshot | None:
    """Query the DB and best-effort write the fresh snapshot to Redis.

    "Best-effort": if Redis is unreachable, the write is logged and
    swallowed rather than raised — callers (policy CRUD, user-status
    update, the lazy refresh-on-miss path in access-event ingest) must
    never fail or 500 just because Redis happens to be down; the cache
    simply stays stale/absent until TTL or the next successful refresh.

    Returns the freshly built snapshot (or `None` if the user no longer
    exists — in which case any stale cache entry is proactively deleted
    rather than left to expire).
    """
    snapshot = build_snapshot(user_repo, policy_repo, user_id)

    if snapshot is None:
        try:
            redis_client.delete(_cache_key(user_id))
        except Exception:
            logger.warning("policy_cache_delete_failed", extra={"user_id": str(user_id)})
        return None

    try:
        redis_client.set(_cache_key(user_id), snapshot.model_dump_json(), ex=ttl_seconds)
    except Exception:
        logger.warning("policy_cache_write_failed", extra={"user_id": str(user_id)})

    return snapshot
