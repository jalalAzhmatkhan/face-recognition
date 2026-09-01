"""Recognition-configs API (EC-BE-04, TSD-edge-cases.md D-4.2/D-10, OQ-6).

Every endpoint declares an explicit `require_role(...)` dependency (see
app/dependencies/auth.py docstring — deny-by-default, NFR-SEC-04). Per the
EC-BE-04 task's explicit acceptance criterion ("VIEWER read-only"): list/read
is open to ALL three roles (ADMIN/OPERATOR/VIEWER) since these overrides are
reference/operational configuration a VIEWER should be able to inspect (e.g.
to understand why a device is behaving a certain way), but create/update/
delete are ADMIN-only — these rows directly change recognition-decision
policy (similarity/liveness thresholds), a strictly more sensitive
configuration surface than access_policies' door-group grants.

A hard DELETE (not a status-transition alias) is used here, same reasoning
as app/routers/access_policies.py: a `recognition_configs` row carries no
FK-referenced or historical meaning once removed (nothing else references
it by id), so the `audit_logs` entry is what preserves history.
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.problem import ProblemError
from app.db.session import get_db
from app.dependencies.auth import CurrentStaff, require_role
from app.models.enums import RecognitionConfigScope, StaffRole
from app.repositories.audit_logs import AuditLogRepository
from app.repositories.recognition_configs import RecognitionConfigRepository
from app.schemas.recognition_configs import (
    RecognitionConfigCreateRequest,
    RecognitionConfigListResponse,
    RecognitionConfigResponse,
    RecognitionConfigUpdateRequest,
)
from app.services import recognition_config_service

router = APIRouter(prefix="/recognition-configs", tags=["recognition-configs"])

READ_ROLES = (StaffRole.ADMIN, StaffRole.OPERATOR, StaffRole.VIEWER)
WRITE_ROLES = (StaffRole.ADMIN,)


def get_recognition_config_repository(
    db: Session = Depends(get_db),
) -> RecognitionConfigRepository:
    """Separate dependency (mirrors get_access_policy_repository) so tests
    can override just the repository with an in-memory fake, without a real
    DB session (see backend/tests/test_recognition_configs_router.py)."""
    return RecognitionConfigRepository(db)


def get_audit_log_repository(db: Session = Depends(get_db)) -> AuditLogRepository:
    return AuditLogRepository(db)


def _not_found(config_id: uuid.UUID) -> ProblemError:
    return ProblemError(
        status_code=404,
        title="Not Found",
        detail=f"Recognition config '{config_id}' does not exist.",
    )


def _conflict(scope: RecognitionConfigScope, scope_ref: str | None, mode: str) -> ProblemError:
    return ProblemError(
        status_code=409,
        title="Conflict",
        detail=(
            f"A recognition_configs override already exists for scope='{scope.value}', "
            f"scope_ref={scope_ref!r}, mode='{mode}'."
        ),
    )


@router.get("", response_model=RecognitionConfigListResponse)
def list_recognition_configs(
    scope: RecognitionConfigScope | None = Query(None),
    scope_ref: str | None = Query(None),
    mode: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current: CurrentStaff = Depends(require_role(*READ_ROLES)),
    repo: RecognitionConfigRepository = Depends(get_recognition_config_repository),
) -> RecognitionConfigListResponse:
    items, total = recognition_config_service.list_configs(
        repo, scope=scope, scope_ref=scope_ref, mode=mode, limit=limit, offset=offset
    )
    return RecognitionConfigListResponse(
        items=[RecognitionConfigResponse.model_validate(c) for c in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=RecognitionConfigResponse, status_code=201)
def create_recognition_config(
    body: RecognitionConfigCreateRequest,
    current: CurrentStaff = Depends(require_role(*WRITE_ROLES)),
    repo: RecognitionConfigRepository = Depends(get_recognition_config_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
) -> RecognitionConfigResponse:
    try:
        config = recognition_config_service.create_config(
            repo,
            audit_repo,
            scope=body.scope,
            scope_ref=body.scope_ref,
            mode=body.mode,
            similarity_threshold=body.similarity_threshold,
            margin=body.margin,
            liveness_threshold=body.liveness_threshold,
            min_frames=body.min_frames,
            created_by_staff_id=current.id,
            actor=str(current.id),
        )
    except recognition_config_service.DuplicateConfigError as exc:
        raise _conflict(exc.scope, exc.scope_ref, exc.mode) from exc
    return RecognitionConfigResponse.model_validate(config)


@router.patch("/{config_id}", response_model=RecognitionConfigResponse)
def update_recognition_config(
    config_id: uuid.UUID,
    body: RecognitionConfigUpdateRequest,
    current: CurrentStaff = Depends(require_role(*WRITE_ROLES)),
    repo: RecognitionConfigRepository = Depends(get_recognition_config_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
) -> RecognitionConfigResponse:
    updates = body.model_dump(exclude_unset=True)
    try:
        config = recognition_config_service.update_config(
            repo, audit_repo, config_id=config_id, updates=updates, actor=str(current.id)
        )
    except recognition_config_service.ConfigNotFoundError as exc:
        raise _not_found(config_id) from exc
    return RecognitionConfigResponse.model_validate(config)


@router.delete("/{config_id}", status_code=204)
def delete_recognition_config(
    config_id: uuid.UUID,
    current: CurrentStaff = Depends(require_role(*WRITE_ROLES)),
    repo: RecognitionConfigRepository = Depends(get_recognition_config_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
) -> None:
    try:
        recognition_config_service.delete_config(
            repo, audit_repo, config_id=config_id, actor=str(current.id)
        )
    except recognition_config_service.ConfigNotFoundError as exc:
        raise _not_found(config_id) from exc
