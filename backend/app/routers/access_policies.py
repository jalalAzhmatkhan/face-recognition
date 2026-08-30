"""Access policies API (BE-10, TSD §4/§7, FR-INF-05).

Every endpoint declares an explicit `require_role(...)` dependency (see
app/dependencies/auth.py docstring — deny-by-default, NFR-SEC-04). Write
endpoints (create/update/delete) are ADMIN-only per BE-10 task
instructions — policies gate physical building access, mirroring
app/routers/devices.py's stricter-than-users posture. List/read is opened to
ADMIN+OPERATOR (not VIEWER — same rationale as devices: operational/security
configuration, not general reference data).

There is no DELETE-as-status-transition alias here (unlike users/devices):
an access_policies row carries no historical/FK-referenced meaning once
removed (access_events never references access_policies), so a hard DELETE
is the correct semantics — the audit_logs entry is what preserves history.
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.problem import ProblemError
from app.core.redis_client import get_redis_client
from app.db.session import get_db
from app.dependencies.auth import CurrentStaff, require_role
from app.models.enums import StaffRole
from app.repositories.access_policies import AccessPolicyRepository
from app.repositories.audit_logs import AuditLogRepository
from app.repositories.users import UserRepository
from app.schemas.access_policies import (
    AccessPolicyCreateRequest,
    AccessPolicyListResponse,
    AccessPolicyResponse,
    AccessPolicyUpdateRequest,
)
from app.services import access_policy_service

router = APIRouter(prefix="/access-policies", tags=["access-policies"])

READ_ROLES = (StaffRole.ADMIN, StaffRole.OPERATOR)
WRITE_ROLES = (StaffRole.ADMIN,)


def get_access_policy_repository(db: Session = Depends(get_db)) -> AccessPolicyRepository:
    """Separate dependency (mirrors get_device_repository) so tests can
    override just the repository with an in-memory fake, without a real DB
    session (see backend/tests/test_access_policies_router.py)."""
    return AccessPolicyRepository(db)


def get_audit_log_repository(db: Session = Depends(get_db)) -> AuditLogRepository:
    return AuditLogRepository(db)


def get_user_repository(db: Session = Depends(get_db)) -> UserRepository:
    return UserRepository(db)


def _not_found(policy_id: uuid.UUID) -> ProblemError:
    return ProblemError(
        status_code=404,
        title="Not Found",
        detail=f"Access policy '{policy_id}' does not exist.",
    )


@router.get("", response_model=AccessPolicyListResponse)
def list_access_policies(
    user_id: uuid.UUID | None = Query(None),
    door_group: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current: CurrentStaff = Depends(require_role(*READ_ROLES)),
    repo: AccessPolicyRepository = Depends(get_access_policy_repository),
) -> AccessPolicyListResponse:
    items, total = access_policy_service.list_policies(
        repo, user_id=user_id, door_group=door_group, limit=limit, offset=offset
    )
    return AccessPolicyListResponse(
        items=[AccessPolicyResponse.model_validate(p) for p in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=AccessPolicyResponse, status_code=201)
def create_access_policy(
    body: AccessPolicyCreateRequest,
    current: CurrentStaff = Depends(require_role(*WRITE_ROLES)),
    repo: AccessPolicyRepository = Depends(get_access_policy_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
    user_repo: UserRepository = Depends(get_user_repository),
    redis_client=Depends(get_redis_client),
) -> AccessPolicyResponse:
    policy = access_policy_service.create_policy(
        repo,
        audit_repo,
        user_repo,
        redis_client,
        user_id=body.user_id,
        group_id=body.group_id,
        door_group=body.door_group,
        allowed=body.allowed,
        valid_from=body.valid_from,
        valid_to=body.valid_to,
        actor=str(current.id),
    )
    return AccessPolicyResponse.model_validate(policy)


@router.patch("/{policy_id}", response_model=AccessPolicyResponse)
def update_access_policy(
    policy_id: uuid.UUID,
    body: AccessPolicyUpdateRequest,
    current: CurrentStaff = Depends(require_role(*WRITE_ROLES)),
    repo: AccessPolicyRepository = Depends(get_access_policy_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
    user_repo: UserRepository = Depends(get_user_repository),
    redis_client=Depends(get_redis_client),
) -> AccessPolicyResponse:
    updates = body.model_dump(exclude_unset=True)
    try:
        policy = access_policy_service.update_policy(
            repo,
            audit_repo,
            user_repo,
            redis_client,
            policy_id=policy_id,
            updates=updates,
            actor=str(current.id),
        )
    except access_policy_service.PolicyNotFoundError as exc:
        raise _not_found(policy_id) from exc
    return AccessPolicyResponse.model_validate(policy)


@router.delete("/{policy_id}", status_code=204)
def delete_access_policy(
    policy_id: uuid.UUID,
    current: CurrentStaff = Depends(require_role(*WRITE_ROLES)),
    repo: AccessPolicyRepository = Depends(get_access_policy_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
    user_repo: UserRepository = Depends(get_user_repository),
    redis_client=Depends(get_redis_client),
) -> None:
    try:
        access_policy_service.delete_policy(
            repo,
            audit_repo,
            user_repo,
            redis_client,
            policy_id=policy_id,
            actor=str(current.id),
        )
    except access_policy_service.PolicyNotFoundError as exc:
        raise _not_found(policy_id) from exc
