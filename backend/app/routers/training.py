"""Training job + model registry API (BE-13, TSD §7, FR-TRN-02/05/06).

**Role simplification (documented per CLAUDE.md's existing precedent —
e.g. auth.router uses local JWT instead of OIDC)**: FSD-AI.md's ACT-05 "ML
Engineer" actor is a role distinct from the staff RBAC roles, but
`app.models.enums.StaffRole` only defines ADMIN/OPERATOR/VIEWER — there is
no separate ML role in this project's auth model, and adding one is out of
scope for BE-13. Every place TSD §7 says "ADMIN/ML" is therefore treated as
ADMIN-only in v1. `GET /models` and `GET /training/jobs/{id}` are read
endpoints and are opened to OPERATOR too (VIEWER also gets `/models`, since
model metadata isn't security-sensitive the way training triggers/promotion
are) — mirrors the read/write role split already established by
`app/routers/access_policies.py` and `app/routers/devices.py`.
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.problem import ProblemError
from app.db.session import get_db
from app.dependencies.auth import CurrentStaff, require_role
from app.models.enums import ModelStage, StaffRole, TrainingJobStatus
from app.repositories.audit_logs import AuditLogRepository
from app.repositories.model_versions import ModelVersionRepository
from app.repositories.training_jobs import TrainingJobRepository
from app.schemas.training import (
    ModelPromoteRequest,
    ModelPromoteResponse,
    ModelVersionListResponse,
    ModelVersionResponse,
    TrainingJobCreateRequest,
    TrainingJobListResponse,
    TrainingJobResponse,
)
from app.services import training_service

router = APIRouter(tags=["training"])

TRIGGER_ROLES = (StaffRole.ADMIN,)
JOB_READ_ROLES = (StaffRole.ADMIN, StaffRole.OPERATOR)
MODEL_READ_ROLES = (StaffRole.ADMIN, StaffRole.OPERATOR, StaffRole.VIEWER)
PROMOTE_ROLES = (StaffRole.ADMIN,)


def get_training_job_repository(db: Session = Depends(get_db)) -> TrainingJobRepository:
    return TrainingJobRepository(db)


def get_model_version_repository(db: Session = Depends(get_db)) -> ModelVersionRepository:
    return ModelVersionRepository(db)


def get_audit_log_repository(db: Session = Depends(get_db)) -> AuditLogRepository:
    return AuditLogRepository(db)


def _job_not_found(job_id: uuid.UUID) -> ProblemError:
    return ProblemError(
        status_code=404, title="Not Found", detail=f"Training job '{job_id}' does not exist."
    )


def _model_not_found(version: str) -> ProblemError:
    return ProblemError(
        status_code=404, title="Not Found", detail=f"Model version '{version}' does not exist."
    )


@router.post("/training/jobs", response_model=TrainingJobResponse, status_code=201)
def create_training_job(
    body: TrainingJobCreateRequest,
    current: CurrentStaff = Depends(require_role(*TRIGGER_ROLES)),
    job_repo: TrainingJobRepository = Depends(get_training_job_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
) -> TrainingJobResponse:
    """FR-TRN-02: manually trigger a training-evaluation job. Automatic
    triggering (TR-09) is out of scope here."""
    job = training_service.create_training_job(
        job_repo,
        audit_repo,
        model_version=body.model_version,
        benchmark_id=body.benchmark_id,
        actor=current.id,
    )
    return TrainingJobResponse.model_validate(job)


@router.get("/training/jobs", response_model=TrainingJobListResponse)
def list_training_jobs(
    status: TrainingJobStatus | None = Query(None),
    model_version: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current: CurrentStaff = Depends(require_role(*JOB_READ_ROLES)),
    job_repo: TrainingJobRepository = Depends(get_training_job_repository),
) -> TrainingJobListResponse:
    """BE-15: server-side training-job history (newest first), closing the
    gap FE-09 documented (it fell back to a browser-localStorage-only list
    because this endpoint didn't exist yet)."""
    jobs, total = training_service.list_training_jobs(
        job_repo, status=status, model_version=model_version, limit=limit, offset=offset
    )
    return TrainingJobListResponse(
        items=[TrainingJobResponse.model_validate(j) for j in jobs],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/training/jobs/{job_id}", response_model=TrainingJobResponse)
def get_training_job(
    job_id: uuid.UUID,
    current: CurrentStaff = Depends(require_role(*JOB_READ_ROLES)),
    job_repo: TrainingJobRepository = Depends(get_training_job_repository),
) -> TrainingJobResponse:
    try:
        job = training_service.get_training_job(job_repo, job_id)
    except training_service.TrainingJobNotFoundError as exc:
        raise _job_not_found(job_id) from exc
    return TrainingJobResponse.model_validate(job)


@router.get("/models", response_model=ModelVersionListResponse)
def list_models(
    stage: ModelStage | None = Query(None),
    current: CurrentStaff = Depends(require_role(*MODEL_READ_ROLES)),
    model_repo: ModelVersionRepository = Depends(get_model_version_repository),
) -> ModelVersionListResponse:
    models = training_service.list_models(model_repo, stage=stage)
    return ModelVersionListResponse(items=[ModelVersionResponse.model_validate(m) for m in models])


@router.get("/models/{version}", response_model=ModelVersionResponse)
def get_model(
    version: str,
    current: CurrentStaff = Depends(require_role(*MODEL_READ_ROLES)),
    model_repo: ModelVersionRepository = Depends(get_model_version_repository),
) -> ModelVersionResponse:
    try:
        model = training_service.get_model(model_repo, version)
    except training_service.ModelVersionNotFoundError as exc:
        raise _model_not_found(version) from exc
    return ModelVersionResponse.model_validate(model)


@router.post("/models/{version}/promote", response_model=ModelPromoteResponse)
def promote_model(
    version: str,
    body: ModelPromoteRequest,
    current: CurrentStaff = Depends(require_role(*PROMOTE_ROLES)),
    model_repo: ModelVersionRepository = Depends(get_model_version_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
    settings: Settings = Depends(get_settings),
) -> ModelPromoteResponse:
    """FR-TRN-05: human-in-the-loop promotion gate. See
    `app/services/training_service.py::promote_model` for the four checks
    (confirmation, CANDIDATE-only, no-recall-regression, latency budget).

    FR-TRN-06 (gallery re-embedding after promotion) is explicitly NOT
    triggered here — that is TR-08, a separate follow-up task.
    """
    try:
        model = training_service.promote_model(
            model_repo,
            audit_repo,
            settings,
            version=version,
            confirm=body.confirm,
            actor=current.id,
        )
    except training_service.ModelVersionNotFoundError as exc:
        raise _model_not_found(version) from exc
    except training_service.ConfirmationRequiredError as exc:
        raise ProblemError(status_code=422, title="Confirmation Required", detail=str(exc)) from exc
    except training_service.PromotionGateError as exc:
        raise ProblemError(
            status_code=409,
            title="Promotion Gate Failed",
            detail="; ".join(exc.reasons),
            extra={"reasons": exc.reasons},
        ) from exc

    return ModelPromoteResponse(
        version=model.version,
        stage=model.stage,
        promoted_by=model.promoted_by,
        promoted_at=model.promoted_at,
    )
