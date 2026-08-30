"""Users business logic (BE-04, FR-USR-01).

Layering per app/main.py docstring: routers (HTTP) -> services (business
logic) -> repositories (data access). This module owns:
  - external_ref uniqueness enforcement (routers translate to 409)
  - the ACTIVE default on creation
  - writing an `audit_logs` entry for create + every status change, so the
    audit trail is the source of truth for "who changed a user's access
    status and when" (TSD audit requirement; enforcement of "non-ACTIVE
    never grants access" itself lands later in the inference/policy layer —
    out of scope here).
"""

import uuid
from typing import Any

from app.models.enums import UserStatus
from app.models.user import User
from app.repositories.audit_logs import AuditLogRepository
from app.repositories.users import UserRepository


class UserNotFoundError(Exception):
    """No user exists with the given id."""


class DuplicateExternalRefError(Exception):
    """`external_ref` already belongs to another user."""

    def __init__(self, external_ref: str) -> None:
        self.external_ref = external_ref
        super().__init__(external_ref)


def get_user(repo: UserRepository, user_id: uuid.UUID) -> User:
    user = repo.get(user_id)
    if user is None:
        raise UserNotFoundError(str(user_id))
    return user


def list_users(
    repo: UserRepository,
    *,
    status: UserStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[User], int]:
    items = repo.list(status=status, limit=limit, offset=offset)
    total = repo.count(status=status)
    return items, total


def _serialize(value: Any) -> Any:
    return value.value if isinstance(value, UserStatus) else value


def create_user(
    repo: UserRepository,
    audit_repo: AuditLogRepository,
    *,
    external_ref: str,
    full_name: str,
    actor: str,
) -> User:
    if repo.get_by_external_ref(external_ref) is not None:
        raise DuplicateExternalRefError(external_ref)

    user = User(external_ref=external_ref, full_name=full_name, status=UserStatus.ACTIVE)
    user = repo.create(user)

    audit_repo.record(
        actor=actor,
        action="user.create",
        entity=f"user:{user.id}",
        payload={
            "external_ref": external_ref,
            "full_name": full_name,
            "status": UserStatus.ACTIVE.value,
        },
    )
    return user


def update_user(
    repo: UserRepository,
    audit_repo: AuditLogRepository,
    *,
    user_id: uuid.UUID,
    updates: dict[str, Any],
    actor: str,
) -> User:
    """`updates` MUST come from `UserUpdateRequest.model_dump(exclude_unset=True)`
    (or an equivalent explicit dict) so an omitted field is never confused
    with a field explicitly cleared to `None`."""
    user = repo.get(user_id)
    if user is None:
        raise UserNotFoundError(str(user_id))

    if "external_ref" in updates and updates["external_ref"] != user.external_ref:
        existing = repo.get_by_external_ref(updates["external_ref"])
        if existing is not None and existing.id != user.id:
            raise DuplicateExternalRefError(updates["external_ref"])

    status_changed = "status" in updates and updates["status"] != user.status
    previous_status = user.status

    if "external_ref" in updates:
        user.external_ref = updates["external_ref"]
    if "full_name" in updates:
        user.full_name = updates["full_name"]
    if "status" in updates:
        user.status = updates["status"]

    user = repo.update(user)

    # Status transitions (especially -> OFFBOARDED) are the important event
    # per FR-USR-01 / TSD audit requirements, so they get a dedicated action
    # name distinct from a plain profile edit.
    if status_changed:
        audit_repo.record(
            actor=actor,
            action="user.status_change",
            entity=f"user:{user.id}",
            payload={"from": previous_status.value, "to": user.status.value},
        )

    other_updates = {k: _serialize(v) for k, v in updates.items() if k != "status"}
    if other_updates:
        audit_repo.record(
            actor=actor,
            action="user.update",
            entity=f"user:{user.id}",
            payload=other_updates,
        )

    return user


def offboard_user(
    repo: UserRepository,
    audit_repo: AuditLogRepository,
    *,
    user_id: uuid.UUID,
    actor: str,
) -> User:
    """Used by `DELETE /users/{id}` (see router docstring): we never
    hard-delete a user, so "delete" is defined as a transition to
    OFFBOARDED, routed through the same audited `update_user` path."""
    return update_user(
        repo,
        audit_repo,
        user_id=user_id,
        updates={"status": UserStatus.OFFBOARDED},
        actor=actor,
    )
