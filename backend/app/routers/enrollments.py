"""Enrollment session API (BE-05, FR-ENR-01/08, FSD-AI.md §8).

Every endpoint declares an explicit `require_role(...)` dependency (see
app/dependencies/auth.py docstring — deny-by-default, NFR-SEC-04).

Transition-endpoint design decision (documented per task BE-05 instructions):
    The FSD state machine has many edges, but only one of them is both (a)
    manually staff-triggered and (b) fully in BE-05 scope: CONSENTED ->
    CAPTURING (starting capture). Re-entering CAPTURING from
    REJECTED_QUALITY after a failed quality check is also just a state
    reset with no media dependency, so it is included too. Every other
    forward edge (CAPTURING -> CAPTURED, QC_RUNNING -> *, EMBEDDING ->
    ENROLLED) is driven by an upload-validation/QC/embedding job that reads
    real media (BE-06/BE-07) and MUST NOT be reachable by a staff-issued
    HTTP call that skips that validation.

    Rather than one endpoint per edge, this router exposes a single generic
    `POST /enrollments/{id}/transition` that takes `{"target_state": ...}`
    and is deliberately restricted, at the router layer, to the small
    `MANUALLY_TRIGGERABLE_TARGETS` allow-list above — NOT to the full state
    machine. The full state machine
    (`app/services/enrollment_state_machine.py`) still does the actual
    `current -> target` legality check underneath, and is the same module
    BE-06/07/08 job code will call directly (bypassing this HTTP allow-list
    entirely, since jobs are not staff-issued requests). This keeps one
    generic endpoint (simpler surface, one RBAC/audit code path) while still
    preventing staff from using it to shortcut job-only transitions.

    `POST /enrollments/{id}/cancel` is kept as its own endpoint rather than
    routed through `/transition` because "cancel from anywhere" is a
    distinct, unconditional operation (no target-state allow-list to check)
    with its own semantics worth a dedicated audit action name.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.aws import get_s3_client
from app.core.config import Settings, get_settings
from app.core.problem import ProblemError
from app.db.session import get_db
from app.dependencies.auth import CurrentStaff, require_role
from app.models.enums import EnrollmentState, StaffRole
from app.repositories.audit_logs import AuditLogRepository
from app.repositories.consents import ConsentRepository
from app.repositories.enrollments import EnrollmentSessionRepository
from app.repositories.media_objects import MediaObjectRepository
from app.repositories.users import UserRepository
from app.schemas.enrollments import (
    ConsentRequest,
    EnrollmentCreateRequest,
    EnrollmentListResponse,
    EnrollmentResponse,
    RevocationResponse,
    TransitionRequest,
)
from app.schemas.media import CompleteResponse, PresignRequest, PresignResponse
from app.services import enrollment_service, media_service, revocation_service
from app.services import enrollment_state_machine as fsm

router = APIRouter(prefix="/enrollments", tags=["enrollments"])

READ_ROLES = (StaffRole.ADMIN, StaffRole.OPERATOR, StaffRole.VIEWER)
WRITE_ROLES = (StaffRole.ADMIN, StaffRole.OPERATOR)
# DELETE (revocation) is stricter than every other write endpoint: it is an
# irreversible action against biometric data (FR-ENR-09, BE-08 task
# instructions), so OPERATOR is deliberately excluded here even though it is
# in WRITE_ROLES for everything else in this router.
REVOKE_ROLES = (StaffRole.ADMIN,)

# See module docstring: the only targets `/transition` is allowed to reach.
# Every other legal state-machine edge is job-driven (BE-06/07) or handled
# by the dedicated `/consent` (-> CONSENTED) and `/cancel` (-> CANCELLED)
# endpoints.
MANUALLY_TRIGGERABLE_TARGETS = frozenset({EnrollmentState.CAPTURING})


def get_enrollment_repository(db: Session = Depends(get_db)) -> EnrollmentSessionRepository:
    """Separate dependency (mirrors get_user_repository) so tests can
    override just the repository with an in-memory fake, without a real DB
    session (see backend/tests/test_enrollments_router.py)."""
    return EnrollmentSessionRepository(db)


def get_consent_repository(db: Session = Depends(get_db)) -> ConsentRepository:
    return ConsentRepository(db)


def get_user_repository_dep(db: Session = Depends(get_db)) -> UserRepository:
    return UserRepository(db)


def get_audit_log_repository(db: Session = Depends(get_db)) -> AuditLogRepository:
    return AuditLogRepository(db)


def get_media_object_repository(db: Session = Depends(get_db)) -> MediaObjectRepository:
    """Separate dependency (mirrors the other `get_*_repository` functions)
    so tests can override it with an in-memory fake (BE-06, see
    backend/tests/test_enrollments_media_router.py)."""
    return MediaObjectRepository(db)


def get_settings_dependency() -> Settings:
    """Thin wrapper around `get_settings()` so tests can override the S3
    bucket/prefix config independently of real env vars (BE-06)."""
    return get_settings()


def get_s3_client_dependency() -> Any:
    """Thin wrapper around `get_s3_client()` so tests can override it with a
    mock/fake boto3 client — no real AWS/MinIO call is ever made from
    automated tests (BE-06)."""
    return get_s3_client()


def _not_found(session_id: uuid.UUID) -> ProblemError:
    return ProblemError(
        status_code=404,
        title="Not Found",
        detail=f"Enrollment session '{session_id}' does not exist.",
    )


def _user_not_found(user_id: uuid.UUID) -> ProblemError:
    return ProblemError(
        status_code=404, title="Not Found", detail=f"User '{user_id}' does not exist."
    )


def _user_not_active(exc: enrollment_service.UserNotActiveError) -> ProblemError:
    # 409 (not 422): the request body itself is well-formed and `user_id`
    # refers to a real resource — the conflict is between the *current
    # state* of that resource (status != ACTIVE) and the operation being
    # requested (FR-ENR-01 requires ACTIVE), which is exactly what 409 is
    # for. 422 is reserved in this API for payload/schema validation
    # failures (see app/core/problem.py's RequestValidationError handler).
    return ProblemError(
        status_code=409,
        title="Conflict",
        detail=(
            f"User '{exc.user_id}' is not ACTIVE (status={exc.status.value}); "
            "an enrollment session can only be created for an ACTIVE user."
        ),
    )


def _invalid_consent_state(exc: enrollment_service.InvalidConsentStateError) -> ProblemError:
    return ProblemError(
        status_code=409,
        title="Conflict",
        detail=(
            f"Enrollment session '{exc.session_id}' is in state "
            f"{exc.current_state.value}; consent can only be recorded while "
            "the session is CREATED."
        ),
    )


def _illegal_transition(exc: fsm.IllegalTransitionError) -> ProblemError:
    return ProblemError(
        status_code=409,
        title="Conflict",
        detail=f"Cannot transition enrollment session from {exc.current} to {exc.target}.",
        extra={"current_state": exc.current.value, "target_state": exc.target.value},
    )


def _session_not_capturing(exc: media_service.SessionNotCapturingError) -> ProblemError:
    return ProblemError(
        status_code=409,
        title="Conflict",
        detail=(
            f"Enrollment session '{exc.session_id}' is in state "
            f"{exc.current_state.value}; this operation is only allowed while the "
            "session is CAPTURING."
        ),
    )


def _media_validation_error(exc: media_service.MediaValidationError) -> ProblemError:
    return ProblemError(status_code=422, title="Unprocessable Entity", detail=exc.detail)


def _media_completion_error(exc: media_service.MediaCompletionError) -> ProblemError:
    return ProblemError(
        status_code=422,
        title="Unprocessable Entity",
        detail="Enrollment media could not be verified; see 'reasons' for details.",
        extra={"reasons": exc.reasons},
    )


@router.post("", response_model=EnrollmentResponse, status_code=201)
def create_enrollment(
    body: EnrollmentCreateRequest,
    current: CurrentStaff = Depends(require_role(*WRITE_ROLES)),
    enrollment_repo: EnrollmentSessionRepository = Depends(get_enrollment_repository),
    user_repo: UserRepository = Depends(get_user_repository_dep),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
) -> EnrollmentResponse:
    try:
        session = enrollment_service.create_session(
            enrollment_repo,
            user_repo,
            audit_repo,
            user_id=body.user_id,
            created_by=current.id,
            actor=str(current.id),
        )
    except enrollment_service.UserNotFoundError as exc:
        raise _user_not_found(body.user_id) from exc
    except enrollment_service.UserNotActiveError as exc:
        raise _user_not_active(exc) from exc
    return EnrollmentResponse.model_validate(session)


@router.get("", response_model=EnrollmentListResponse)
def list_enrollments(
    user_id: uuid.UUID | None = Query(None),
    state: EnrollmentState | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current: CurrentStaff = Depends(require_role(*READ_ROLES)),
    enrollment_repo: EnrollmentSessionRepository = Depends(get_enrollment_repository),
) -> EnrollmentListResponse:
    items, total = enrollment_service.list_sessions(
        enrollment_repo, user_id=user_id, state=state, limit=limit, offset=offset
    )
    return EnrollmentListResponse(
        items=[EnrollmentResponse.model_validate(s) for s in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{session_id}", response_model=EnrollmentResponse)
def get_enrollment(
    session_id: uuid.UUID,
    current: CurrentStaff = Depends(require_role(*READ_ROLES)),
    enrollment_repo: EnrollmentSessionRepository = Depends(get_enrollment_repository),
) -> EnrollmentResponse:
    try:
        session = enrollment_service.get_session(enrollment_repo, session_id)
    except enrollment_service.EnrollmentNotFoundError as exc:
        raise _not_found(session_id) from exc
    return EnrollmentResponse.model_validate(session)


@router.post("/{session_id}/consent", response_model=EnrollmentResponse)
def grant_consent(
    session_id: uuid.UUID,
    body: ConsentRequest,
    current: CurrentStaff = Depends(require_role(*WRITE_ROLES)),
    enrollment_repo: EnrollmentSessionRepository = Depends(get_enrollment_repository),
    consent_repo: ConsentRepository = Depends(get_consent_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
) -> EnrollmentResponse:
    try:
        session = enrollment_service.grant_consent(
            enrollment_repo,
            consent_repo,
            audit_repo,
            session_id=session_id,
            consent_version=body.consent_version,
            actor=str(current.id),
        )
    except enrollment_service.EnrollmentNotFoundError as exc:
        raise _not_found(session_id) from exc
    except enrollment_service.InvalidConsentStateError as exc:
        raise _invalid_consent_state(exc) from exc
    return EnrollmentResponse.model_validate(session)


@router.post("/{session_id}/transition", response_model=EnrollmentResponse)
def transition_enrollment(
    session_id: uuid.UUID,
    body: TransitionRequest,
    current: CurrentStaff = Depends(require_role(*WRITE_ROLES)),
    enrollment_repo: EnrollmentSessionRepository = Depends(get_enrollment_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
) -> EnrollmentResponse:
    if body.target_state not in MANUALLY_TRIGGERABLE_TARGETS:
        raise ProblemError(
            status_code=409,
            title="Conflict",
            detail=(
                f"Target state '{body.target_state.value}' is not reachable via this "
                "endpoint. Transitions past CAPTURING are driven by media upload/QC/"
                "embedding jobs, not by a direct staff-issued transition."
            ),
        )
    try:
        session = enrollment_service.transition_session(
            enrollment_repo,
            audit_repo,
            session_id=session_id,
            target_state=body.target_state,
            actor=str(current.id),
        )
    except enrollment_service.EnrollmentNotFoundError as exc:
        raise _not_found(session_id) from exc
    except fsm.IllegalTransitionError as exc:
        raise _illegal_transition(exc) from exc
    return EnrollmentResponse.model_validate(session)


@router.delete("/{session_id}", response_model=RevocationResponse, status_code=202)
def revoke_enrollment(
    session_id: uuid.UUID,
    current: CurrentStaff = Depends(require_role(*REVOKE_ROLES)),
    enrollment_repo: EnrollmentSessionRepository = Depends(get_enrollment_repository),
    user_repo: UserRepository = Depends(get_user_repository_dep),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
) -> RevocationResponse:
    """BE-08: revoke a completed enrollment (FR-ENR-09, NFR-SEC-03, ASM-12).

    ADMIN only (see `REVOKE_ROLES` above). Only legal while the session is
    ENROLLED (state-machine-enforced; any other current state -> 409). The
    security-critical effects (ENROLLED -> REVOKED, `user.status =
    OFFBOARDED`, audit entry) happen synchronously in
    `revocation_service.revoke_enrollment` before this returns, so a
    revoked user is unrecognized immediately — physical deletion of
    embeddings/media and the user tombstone follow asynchronously (dispatched
    by that same call), which is why this returns 202, not 200/204.
    """
    try:
        session = revocation_service.revoke_enrollment(
            enrollment_repo,
            user_repo,
            audit_repo,
            session_id=session_id,
            actor=str(current.id),
        )
    except enrollment_service.EnrollmentNotFoundError as exc:
        raise _not_found(session_id) from exc
    except fsm.IllegalTransitionError as exc:
        raise _illegal_transition(exc) from exc
    return RevocationResponse(id=session.id, state=session.state)


@router.post("/{session_id}/media/presign", response_model=PresignResponse, status_code=201)
def presign_enrollment_media(
    session_id: uuid.UUID,
    body: PresignRequest,
    current: CurrentStaff = Depends(require_role(*WRITE_ROLES)),
    enrollment_repo: EnrollmentSessionRepository = Depends(get_enrollment_repository),
    media_repo: MediaObjectRepository = Depends(get_media_object_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
    s3_client: Any = Depends(get_s3_client_dependency),
    settings: Settings = Depends(get_settings_dependency),
) -> PresignResponse:
    """BE-06: issue a presigned S3 PUT URL (TSD §7). Media bytes never pass
    through this backend (FR-ENR-04, NFR-PRF-03) — the frontend PUTs
    directly to the returned `upload_url`."""
    try:
        result = media_service.request_presign(
            enrollment_repo,
            media_repo,
            audit_repo,
            s3_client,
            settings,
            session_id=session_id,
            kind=body.kind,
            content_type=body.content_type,
            size=body.size,
            sha256=body.sha256,
            actor=str(current.id),
            variant=body.variant,
        )
    except enrollment_service.EnrollmentNotFoundError as exc:
        raise _not_found(session_id) from exc
    except media_service.SessionNotCapturingError as exc:
        raise _session_not_capturing(exc) from exc
    except media_service.MediaValidationError as exc:
        raise _media_validation_error(exc) from exc
    return PresignResponse(
        upload_url=result.upload_url, s3_key=result.media.s3_key, expires_at=result.expires_at
    )


@router.post("/{session_id}/complete", response_model=CompleteResponse, status_code=202)
def complete_enrollment_media(
    session_id: uuid.UUID,
    current: CurrentStaff = Depends(require_role(*WRITE_ROLES)),
    enrollment_repo: EnrollmentSessionRepository = Depends(get_enrollment_repository),
    media_repo: MediaObjectRepository = Depends(get_media_object_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
    s3_client: Any = Depends(get_s3_client_dependency),
) -> CompleteResponse:
    """BE-06: validate uploaded media via S3 HEAD (never by trusting the
    client) and, on success, transition CAPTURING -> CAPTURED -> QC_RUNNING
    in one call (FR-ENR-05, TSD §7). On any validation failure the session
    state is left untouched and a 422 problem+json lists every reason."""
    try:
        session = media_service.complete_enrollment(
            enrollment_repo,
            media_repo,
            audit_repo,
            s3_client,
            session_id=session_id,
            actor=str(current.id),
        )
    except enrollment_service.EnrollmentNotFoundError as exc:
        raise _not_found(session_id) from exc
    except media_service.SessionNotCapturingError as exc:
        raise _session_not_capturing(exc) from exc
    except media_service.MediaCompletionError as exc:
        raise _media_completion_error(exc) from exc
    return CompleteResponse(id=session.id, state=session.state)


@router.post("/{session_id}/cancel", response_model=EnrollmentResponse)
def cancel_enrollment(
    session_id: uuid.UUID,
    current: CurrentStaff = Depends(require_role(*WRITE_ROLES)),
    enrollment_repo: EnrollmentSessionRepository = Depends(get_enrollment_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
) -> EnrollmentResponse:
    try:
        session = enrollment_service.cancel_session(
            enrollment_repo, audit_repo, session_id=session_id, actor=str(current.id)
        )
    except enrollment_service.EnrollmentNotFoundError as exc:
        raise _not_found(session_id) from exc
    except fsm.IllegalTransitionError as exc:
        raise _illegal_transition(exc) from exc
    return EnrollmentResponse.model_validate(session)
