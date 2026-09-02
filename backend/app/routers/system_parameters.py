"""System Parameter admin-menu API.

Read is open to ADMIN/OPERATOR/VIEWER — the Enrollment capture wizard needs
the current effective thresholds for every role that can perform
enrollment (OPERATOR included), and a VIEWER inspecting why capture
behaves a certain way is the same "reference config, not sensitive"
reasoning `app/routers/recognition_configs.py` already uses. Write is
ADMIN-only, same as every other operational-policy surface in this API.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import CurrentStaff, require_role
from app.models.enums import StaffRole
from app.repositories.audit_logs import AuditLogRepository
from app.repositories.system_parameters import SystemParameterRepository
from app.schemas.system_parameters import EnrollmentQualityParams, EnrollmentQualityParamsResponse
from app.services import system_parameter_service

router = APIRouter(prefix="/system-parameters", tags=["system-parameters"])

READ_ROLES = (StaffRole.ADMIN, StaffRole.OPERATOR, StaffRole.VIEWER)
WRITE_ROLES = (StaffRole.ADMIN,)


def get_system_parameter_repository(db: Session = Depends(get_db)) -> SystemParameterRepository:
    return SystemParameterRepository(db)


def get_audit_log_repository(db: Session = Depends(get_db)) -> AuditLogRepository:
    return AuditLogRepository(db)


def _to_response(
    params: EnrollmentQualityParams,
    *,
    updated_by: uuid.UUID | None,
    updated_at: datetime | None,
    is_default: bool,
) -> EnrollmentQualityParamsResponse:
    # Spread the model rather than listing fields by hand: the response
    # schema EXTENDS `EnrollmentQualityParams`, so hand-listing meant every
    # new parameter silently came back as its schema default no matter what
    # was saved (found live when the pose-sensitivity fields were added).
    return EnrollmentQualityParamsResponse(
        **params.model_dump(),
        updated_by=updated_by,
        updated_at=updated_at,
        is_default=is_default,
    )


@router.get("/enrollment-quality", response_model=EnrollmentQualityParamsResponse)
def get_enrollment_quality(
    current: CurrentStaff = Depends(require_role(*READ_ROLES)),
    repo: SystemParameterRepository = Depends(get_system_parameter_repository),
) -> EnrollmentQualityParamsResponse:
    params, row = system_parameter_service.get_enrollment_quality_params(repo)
    return _to_response(
        params,
        updated_by=row.updated_by if row else None,
        updated_at=row.updated_at if row else None,
        is_default=row is None,
    )


@router.put("/enrollment-quality", response_model=EnrollmentQualityParamsResponse)
def update_enrollment_quality(
    body: EnrollmentQualityParams,
    current: CurrentStaff = Depends(require_role(*WRITE_ROLES)),
    repo: SystemParameterRepository = Depends(get_system_parameter_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
) -> EnrollmentQualityParamsResponse:
    row = system_parameter_service.update_enrollment_quality_params(
        repo, audit_repo, params=body, actor=current.id
    )
    return _to_response(
        body, updated_by=row.updated_by, updated_at=row.updated_at, is_default=False
    )
