"""Users CRUD + status endpoints (BE-04, FR-USR-01).

Every endpoint declares an explicit `require_role(...)` dependency (see
app/dependencies/auth.py docstring — deny-by-default, NFR-SEC-04).

DELETE decision (documented per task BE-04 instructions):
    Users carry biometric/PII-linked data (enrollments, embeddings, media —
    TSD privacy design), so this API never hard-deletes a `users` row.
    `DELETE /users/{id}` is implemented as an ALIAS for transitioning the
    user to `OFFBOARDED` (idempotent: deleting an already-offboarded user
    just re-confirms that state) rather than rejecting the verb outright.
    Rationale: OFFBOARDED already carries the "never grant access" semantics
    FR-USR-01 requires, a DELETE alias keeps standard REST client
    expectations working (DELETE removes access, not history), and it goes
    through the exact same audited `update_user` path as
    `PATCH /users/{id} {"status": "OFFBOARDED"}` — so no separate code path
    to keep in sync. Any real erasure (media/embeddings/DB row) is out of
    scope for BE-04 and belongs to the retention/deletion-cascade task
    (BE-08) per NFR-SEC-03.
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.problem import ProblemError
from app.db.session import get_db
from app.dependencies.auth import CurrentStaff, require_role
from app.models.enums import StaffRole, UserStatus
from app.repositories.audit_logs import AuditLogRepository
from app.repositories.users import UserRepository
from app.schemas.users import (
    UserCreateRequest,
    UserListResponse,
    UserResponse,
    UserUpdateRequest,
)
from app.services import user_service

router = APIRouter(prefix="/users", tags=["users"])

READ_ROLES = (StaffRole.ADMIN, StaffRole.OPERATOR, StaffRole.VIEWER)
WRITE_ROLES = (StaffRole.ADMIN, StaffRole.OPERATOR)


def get_user_repository(db: Session = Depends(get_db)) -> UserRepository:
    """Separate dependency (mirrors get_staff_account_repository) so tests
    can override just the repository with an in-memory fake, without a real
    DB session (see backend/tests/test_users_router.py)."""
    return UserRepository(db)


def get_audit_log_repository(db: Session = Depends(get_db)) -> AuditLogRepository:
    return AuditLogRepository(db)


def _not_found(user_id: uuid.UUID) -> ProblemError:
    return ProblemError(
        status_code=404, title="Not Found", detail=f"User '{user_id}' does not exist."
    )


def _conflict(external_ref: str) -> ProblemError:
    return ProblemError(
        status_code=409,
        title="Conflict",
        detail=f"external_ref '{external_ref}' is already in use by another user.",
    )


@router.get("", response_model=UserListResponse)
def list_users(
    status_filter: UserStatus | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current: CurrentStaff = Depends(require_role(*READ_ROLES)),
    repo: UserRepository = Depends(get_user_repository),
) -> UserListResponse:
    items, total = user_service.list_users(repo, status=status_filter, limit=limit, offset=offset)
    return UserListResponse(
        items=[UserResponse.model_validate(u) for u in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=UserResponse, status_code=201)
def create_user(
    body: UserCreateRequest,
    current: CurrentStaff = Depends(require_role(*WRITE_ROLES)),
    repo: UserRepository = Depends(get_user_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
) -> UserResponse:
    try:
        user = user_service.create_user(
            repo,
            audit_repo,
            external_ref=body.external_ref,
            full_name=body.full_name,
            actor=str(current.id),
        )
    except user_service.DuplicateExternalRefError as exc:
        raise _conflict(exc.external_ref) from exc
    return UserResponse.model_validate(user)


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: uuid.UUID,
    current: CurrentStaff = Depends(require_role(*READ_ROLES)),
    repo: UserRepository = Depends(get_user_repository),
) -> UserResponse:
    try:
        user = user_service.get_user(repo, user_id)
    except user_service.UserNotFoundError as exc:
        raise _not_found(user_id) from exc
    return UserResponse.model_validate(user)


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: uuid.UUID,
    body: UserUpdateRequest,
    current: CurrentStaff = Depends(require_role(*WRITE_ROLES)),
    repo: UserRepository = Depends(get_user_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
) -> UserResponse:
    updates = body.model_dump(exclude_unset=True)
    try:
        user = user_service.update_user(
            repo, audit_repo, user_id=user_id, updates=updates, actor=str(current.id)
        )
    except user_service.UserNotFoundError as exc:
        raise _not_found(user_id) from exc
    except user_service.DuplicateExternalRefError as exc:
        raise _conflict(exc.external_ref) from exc
    return UserResponse.model_validate(user)


@router.delete("/{user_id}", response_model=UserResponse)
def delete_user(
    user_id: uuid.UUID,
    current: CurrentStaff = Depends(require_role(*WRITE_ROLES)),
    repo: UserRepository = Depends(get_user_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
) -> UserResponse:
    """Alias for `PATCH {"status": "OFFBOARDED"}` — see module docstring for
    why this never hard-deletes the row."""
    try:
        user = user_service.offboard_user(repo, audit_repo, user_id=user_id, actor=str(current.id))
    except user_service.UserNotFoundError as exc:
        raise _not_found(user_id) from exc
    return UserResponse.model_validate(user)
