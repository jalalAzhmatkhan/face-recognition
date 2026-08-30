"""Access-event ingest + door-decision logic (BE-10, TSD §2.2/§4/§7,
FR-INF-01..06, FR-MON-01).

`ingest_access_event` ALWAYS persists an `access_events` row — a full audit
trail of every recognition attempt regardless of outcome (task BE-10 point
1). The effective door decision (`door_command_issued`) is computed
SEPARATELY and is fail-secure by construction:

    door_command_issued = True  IFF ALL of:
      1. decision == GRANTED
      2. matched_user_id is present
      3. a cached policy snapshot exists for that user
         (policy_cache.get_cached_snapshot — a pure Redis read, NEVER a
         direct DB fallback; a cache MISS is fail-secure DENY per TSD §2.2 /
         FR-INF-05, even though the DB might well have the answer)
      4. snapshot.status == ACTIVE
      5. at least one snapshot policy has door_group == the requesting
         device's own door_group, allowed == True, and "now" falls inside
         [valid_from, valid_to] (an unset bound is treated as unbounded on
         that side)

Any other combination — DENIED/UNKNOWN/SPOOF_SUSPECTED, a cache miss, a
SUSPENDED/OFFBOARDED user, or no matching door_group policy — yields
`door_command_issued = False` WITHOUT raising: this endpoint never errors
just because the door didn't open, since "attempted but not granted" is
itself a normal, auditable outcome.

On a cache miss, a best-effort LAZY `refresh_cache` is fired so the *next*
request for that user has a chance of a cache hit. This deliberately does
NOT block or change the *current* request's fail-secure DENY — blocking on
a DB read before deciding would defeat the entire point of caching, which
is resilience when the DB is slow/down (see app/services/policy_cache.py).
"""

import logging
import uuid
from datetime import UTC, datetime

from app.models.access_event import AccessEvent
from app.models.device import Device
from app.models.enums import AccessDecision, UserStatus
from app.repositories.access_events import AccessEventRepository
from app.repositories.access_policies import AccessPolicyRepository
from app.repositories.users import UserRepository
from app.services import policy_cache
from app.services.policy_cache import PolicySnapshot, PolicySnapshotEntry, RedisLike

logger = logging.getLogger(__name__)


def dispatch_door_command(*, device_id: uuid.UUID, door_group: str) -> None:
    """v1 simplification (ASM-02: the physical door-controller/hardware
    integration is out of scope / TBD). This function does NOT talk to any
    real hardware or door-controller API — it only emits a structured log so
    "a door command was issued" stays observable. It exists as the single
    seam a future hardware integration replaces, so callers never need to
    change when that integration lands."""
    logger.info(
        "door_command_issued",
        extra={"device_id": str(device_id), "door_group": door_group},
    )


def _policy_covers_now(entry: PolicySnapshotEntry, *, now: datetime) -> bool:
    if entry.valid_from is not None and now < entry.valid_from:
        return False
    if entry.valid_to is not None and now > entry.valid_to:
        return False
    return True


def _decide_door_command(
    snapshot: PolicySnapshot | None, *, door_group: str, now: datetime
) -> bool:
    if snapshot is None or snapshot.status != UserStatus.ACTIVE:
        return False
    return any(
        entry.door_group == door_group and entry.allowed and _policy_covers_now(entry, now=now)
        for entry in snapshot.policies
    )


def ingest_access_event(
    event_repo: AccessEventRepository,
    user_repo: UserRepository,
    policy_repo: AccessPolicyRepository,
    redis_client: RedisLike,
    *,
    device: Device,
    decision: AccessDecision,
    matched_user_id: uuid.UUID | None,
    similarity: float | None,
    liveness_score: float | None,
    model_version: str | None,
    latency_ms: int | None,
    frame_media_id: uuid.UUID | None,
) -> AccessEvent:
    door_command_issued = False

    if decision == AccessDecision.GRANTED and matched_user_id is not None:
        snapshot = policy_cache.get_cached_snapshot(redis_client, matched_user_id)
        if snapshot is None:
            # Fail-secure for *this* request (door_command_issued stays
            # False); best-effort lazy refresh so the *next* request has a
            # chance of a cache hit. Never let a refresh failure here break
            # event ingestion.
            try:
                policy_cache.refresh_cache(redis_client, user_repo, policy_repo, matched_user_id)
            except Exception:
                logger.warning(
                    "policy_cache_lazy_refresh_failed",
                    extra={"user_id": str(matched_user_id)},
                )
        else:
            door_command_issued = _decide_door_command(
                snapshot, door_group=device.door_group, now=datetime.now(UTC)
            )

    event = AccessEvent(
        device_id=device.id,
        decision=decision,
        matched_user_id=matched_user_id,
        similarity=similarity,
        liveness_score=liveness_score,
        model_version=model_version,
        latency_ms=latency_ms,
        frame_media_id=frame_media_id,
        door_command_issued=door_command_issued,
    )
    event = event_repo.create(event)

    if door_command_issued:
        dispatch_door_command(device_id=device.id, door_group=device.door_group)

    return event


def list_access_events(
    repo: AccessEventRepository,
    *,
    device_id: uuid.UUID | None = None,
    decision: AccessDecision | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AccessEvent], int]:
    items = repo.list(
        device_id=device_id,
        decision=decision,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
        limit=limit,
        offset=offset,
    )
    total = repo.count(
        device_id=device_id,
        decision=decision,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
    )
    return items, total
