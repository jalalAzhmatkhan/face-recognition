"""Access-policy CRUD business logic (BE-10, TSD §4/§7, FR-INF-05).

Layering per app/main.py docstring: routers (HTTP) -> services (business
logic) -> repositories (data access). This module owns:
  - writing an `audit_logs` entry for every create/update/delete (same
    pattern as app/services/user_service.py / app/services/device_service.py),
  - proactively refreshing the affected user's Redis policy-snapshot cache
    (app/services/policy_cache.py) after every write that is scoped to a
    concrete `user_id`, so the change is effective well inside the <=30s
    cache TTL rather than waiting for passive expiry (FR-INF-05).

A policy scoped only by `group_id` (no `user_id`) has no cache entry to
refresh in v1 — see app/services/policy_cache.py's module docstring for why
group-scoped policies aren't resolved into any user's snapshot yet.
"""

import uuid
from datetime import datetime
from typing import Any

from app.models.access_policy import AccessPolicy
from app.repositories.access_policies import AccessPolicyRepository
from app.repositories.audit_logs import AuditLogRepository
from app.repositories.users import UserRepository
from app.services import policy_cache
from app.services.policy_cache import RedisLike


class PolicyNotFoundError(Exception):
    """No `access_policies` row exists with the given id."""


def _serialize(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def _refresh_if_user_scoped(
    redis_client: RedisLike,
    user_repo: UserRepository,
    policy_repo: AccessPolicyRepository,
    user_id: uuid.UUID | None,
) -> None:
    if user_id is not None:
        policy_cache.refresh_cache(redis_client, user_repo, policy_repo, user_id)


def list_policies(
    repo: AccessPolicyRepository,
    *,
    user_id: uuid.UUID | None = None,
    door_group: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AccessPolicy], int]:
    items = repo.list(user_id=user_id, door_group=door_group, limit=limit, offset=offset)
    total = repo.count(user_id=user_id, door_group=door_group)
    return items, total


def create_policy(
    repo: AccessPolicyRepository,
    audit_repo: AuditLogRepository,
    user_repo: UserRepository,
    redis_client: RedisLike,
    *,
    user_id: uuid.UUID | None,
    group_id: uuid.UUID | None,
    door_group: str,
    allowed: bool,
    valid_from: datetime | None,
    valid_to: datetime | None,
    actor: str,
) -> AccessPolicy:
    policy = AccessPolicy(
        user_id=user_id,
        group_id=group_id,
        door_group=door_group,
        allowed=allowed,
        valid_from=valid_from,
        valid_to=valid_to,
    )
    policy = repo.create(policy)

    audit_repo.record(
        actor=actor,
        action="access_policy.create",
        entity=f"access_policy:{policy.id}",
        payload={
            "user_id": str(user_id) if user_id else None,
            "group_id": str(group_id) if group_id else None,
            "door_group": door_group,
            "allowed": allowed,
            "valid_from": _serialize(valid_from),
            "valid_to": _serialize(valid_to),
        },
    )
    _refresh_if_user_scoped(redis_client, user_repo, repo, user_id)
    return policy


def update_policy(
    repo: AccessPolicyRepository,
    audit_repo: AuditLogRepository,
    user_repo: UserRepository,
    redis_client: RedisLike,
    *,
    policy_id: uuid.UUID,
    updates: dict[str, Any],
    actor: str,
) -> AccessPolicy:
    """`updates` MUST come from `AccessPolicyUpdateRequest.model_dump(exclude_unset=True)`
    (mirrors app/services/user_service.py's `update_user`)."""
    policy = repo.get(policy_id)
    if policy is None:
        raise PolicyNotFoundError(str(policy_id))

    if "allowed" in updates:
        policy.allowed = updates["allowed"]
    if "valid_from" in updates:
        policy.valid_from = updates["valid_from"]
    if "valid_to" in updates:
        policy.valid_to = updates["valid_to"]

    policy = repo.update(policy)

    audit_repo.record(
        actor=actor,
        action="access_policy.update",
        entity=f"access_policy:{policy.id}",
        payload={k: _serialize(v) for k, v in updates.items()},
    )
    _refresh_if_user_scoped(redis_client, user_repo, repo, policy.user_id)
    return policy


def delete_policy(
    repo: AccessPolicyRepository,
    audit_repo: AuditLogRepository,
    user_repo: UserRepository,
    redis_client: RedisLike,
    *,
    policy_id: uuid.UUID,
    actor: str,
) -> None:
    policy = repo.get(policy_id)
    if policy is None:
        raise PolicyNotFoundError(str(policy_id))

    affected_user_id = policy.user_id
    repo.delete(policy)

    audit_repo.record(
        actor=actor,
        action="access_policy.delete",
        entity=f"access_policy:{policy_id}",
        payload={"user_id": str(affected_user_id) if affected_user_id else None},
    )
    _refresh_if_user_scoped(redis_client, user_repo, repo, affected_user_id)
