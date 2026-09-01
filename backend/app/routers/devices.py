"""Device registry API (BE-09, FR-USR-04, TSD §7).

Every staff-facing endpoint declares an explicit `require_role(...)`
dependency (see app/dependencies/auth.py docstring — deny-by-default,
NFR-SEC-04). `POST /devices/{id}/heartbeat` is the one exception: it is
called by the device itself, authenticated via
`app/dependencies/device_auth.get_current_device` (a per-device token, not a
staff JWT) rather than any staff role.

DELETE decision (documented per task BE-09 instructions, mirrors
app/routers/users.py's DELETE-as-status-transition rationale):
    `access_events` rows reference `device_id`, so this API never
    hard-deletes a `devices` row. `DELETE /devices/{id}` is an alias for
    transitioning the device to `DISABLED` (idempotent), going through the
    same audited `update_device` path as
    `PATCH /devices/{id} {"status": "DISABLED"}`.
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.problem import ProblemError
from app.db.session import get_db
from app.dependencies.auth import CurrentStaff, require_role
from app.dependencies.device_auth import get_current_device
from app.models.device import Device
from app.models.enums import DeviceStatus, StaffRole
from app.repositories.audit_logs import AuditLogRepository
from app.repositories.devices import DeviceRepository
from app.schemas.devices import (
    DeviceCreateRequest,
    DeviceCredentialIssuedResponse,
    DeviceListResponse,
    DeviceResponse,
    DeviceUpdateRequest,
    HeartbeatResponse,
)
from app.services import device_service

router = APIRouter(prefix="/devices", tags=["devices"])

# Devices are operational/security infra rather than general reference data,
# so — unlike app/routers/users.py's READ_ROLES — VIEWER is deliberately
# excluded from read access here (task BE-09 instructions: "role ADMIN/
# OPERATOR boleh baca").
READ_ROLES = (StaffRole.ADMIN, StaffRole.OPERATOR)
# Every write endpoint (register, rotate-credential, update, disable) is
# ADMIN-only per task BE-09 instructions — devices gate physical building
# access, so this is stricter than users/enrollments' ADMIN+OPERATOR
# WRITE_ROLES.
WRITE_ROLES = (StaffRole.ADMIN,)


def get_device_repository(db: Session = Depends(get_db)) -> DeviceRepository:
    """Separate dependency (mirrors get_user_repository) so tests can
    override just the repository with an in-memory fake, without a real DB
    session (see backend/tests/test_devices_router.py)."""
    return DeviceRepository(db)


def get_audit_log_repository(db: Session = Depends(get_db)) -> AuditLogRepository:
    return AuditLogRepository(db)


def get_settings_dependency() -> Settings:
    """Thin wrapper around `get_settings()` so tests can override the
    heartbeat-staleness threshold independently of real env vars."""
    return get_settings()


def _not_found(device_id: uuid.UUID) -> ProblemError:
    return ProblemError(
        status_code=404, title="Not Found", detail=f"Device '{device_id}' does not exist."
    )


def _device_mismatch(path_id: uuid.UUID, token_device: Device) -> ProblemError:
    return ProblemError(
        status_code=403,
        title="Forbidden",
        detail=(
            f"Device credential does not authorize heartbeats for device '{path_id}' "
            f"(token belongs to device '{token_device.id}')."
        ),
    )


@router.get("", response_model=DeviceListResponse)
def list_devices(
    status_filter: DeviceStatus | None = Query(None, alias="status"),
    door_group: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current: CurrentStaff = Depends(require_role(*READ_ROLES)),
    repo: DeviceRepository = Depends(get_device_repository),
    settings: Settings = Depends(get_settings_dependency),
) -> DeviceListResponse:
    items, total = device_service.list_devices(
        repo, status=status_filter, door_group=door_group, limit=limit, offset=offset
    )
    return DeviceListResponse(
        items=[
            DeviceResponse.from_device(
                d, stale_after_seconds=settings.device_heartbeat_stale_after_seconds
            )
            for d in items
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=DeviceCredentialIssuedResponse, status_code=201)
def register_device(
    body: DeviceCreateRequest,
    current: CurrentStaff = Depends(require_role(*WRITE_ROLES)),
    repo: DeviceRepository = Depends(get_device_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
    settings: Settings = Depends(get_settings_dependency),
) -> DeviceCredentialIssuedResponse:
    """Register a new device. The response's `credential` field is the
    plaintext device bearer token — returned exactly once (BE-09 task
    instructions); it is never persisted or logged."""
    issued = device_service.register_device(
        repo,
        audit_repo,
        name=body.name,
        door_group=body.door_group,
        actor=str(current.id),
        device_class=body.device_class,
        commissioning_checklist=body.commissioning_checklist,
    )
    return DeviceCredentialIssuedResponse.from_issued(
        issued.device,
        credential=issued.plaintext_token,
        stale_after_seconds=settings.device_heartbeat_stale_after_seconds,
    )


@router.get("/{device_id}", response_model=DeviceResponse)
def get_device(
    device_id: uuid.UUID,
    current: CurrentStaff = Depends(require_role(*READ_ROLES)),
    repo: DeviceRepository = Depends(get_device_repository),
    settings: Settings = Depends(get_settings_dependency),
) -> DeviceResponse:
    try:
        device = device_service.get_device(repo, device_id)
    except device_service.DeviceNotFoundError as exc:
        raise _not_found(device_id) from exc
    return DeviceResponse.from_device(
        device, stale_after_seconds=settings.device_heartbeat_stale_after_seconds
    )


@router.post("/{device_id}/heartbeat", response_model=HeartbeatResponse)
def heartbeat(
    device_id: uuid.UUID,
    current_device: Device = Depends(get_current_device),
    repo: DeviceRepository = Depends(get_device_repository),
) -> HeartbeatResponse:
    """Called by the device itself (device-credential auth, NOT staff JWT)
    to report liveness. Updates `last_heartbeat_at` and sets status to
    ONLINE (FR-USR-04)."""
    if current_device.id != device_id:
        raise _device_mismatch(device_id, current_device)
    device = device_service.record_heartbeat(repo, device=current_device)
    return HeartbeatResponse(
        id=device.id, status=device.status, last_heartbeat_at=device.last_heartbeat_at
    )


@router.post("/{device_id}/rotate-credential", response_model=DeviceCredentialIssuedResponse)
def rotate_credential(
    device_id: uuid.UUID,
    current: CurrentStaff = Depends(require_role(*WRITE_ROLES)),
    repo: DeviceRepository = Depends(get_device_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
    settings: Settings = Depends(get_settings_dependency),
) -> DeviceCredentialIssuedResponse:
    """Rotate a device's credential: the old token stops working immediately
    (see app/services/device_service.rotate_credential), and the new
    plaintext token is returned exactly once."""
    try:
        issued = device_service.rotate_credential(
            repo, audit_repo, device_id=device_id, actor=str(current.id)
        )
    except device_service.DeviceNotFoundError as exc:
        raise _not_found(device_id) from exc
    return DeviceCredentialIssuedResponse.from_issued(
        issued.device,
        credential=issued.plaintext_token,
        stale_after_seconds=settings.device_heartbeat_stale_after_seconds,
    )


@router.patch("/{device_id}", response_model=DeviceResponse)
def update_device(
    device_id: uuid.UUID,
    body: DeviceUpdateRequest,
    current: CurrentStaff = Depends(require_role(*WRITE_ROLES)),
    repo: DeviceRepository = Depends(get_device_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
    settings: Settings = Depends(get_settings_dependency),
) -> DeviceResponse:
    updates = body.model_dump(exclude_unset=True)
    try:
        device = device_service.update_device(
            repo, audit_repo, device_id=device_id, updates=updates, actor=str(current.id)
        )
    except device_service.DeviceNotFoundError as exc:
        raise _not_found(device_id) from exc
    return DeviceResponse.from_device(
        device, stale_after_seconds=settings.device_heartbeat_stale_after_seconds
    )


@router.delete("/{device_id}", response_model=DeviceResponse)
def delete_device(
    device_id: uuid.UUID,
    current: CurrentStaff = Depends(require_role(*WRITE_ROLES)),
    repo: DeviceRepository = Depends(get_device_repository),
    audit_repo: AuditLogRepository = Depends(get_audit_log_repository),
    settings: Settings = Depends(get_settings_dependency),
) -> DeviceResponse:
    """Alias for `PATCH {"status": "DISABLED"}` — see module docstring for
    why this never hard-deletes the row."""
    try:
        device = device_service.disable_device(
            repo, audit_repo, device_id=device_id, actor=str(current.id)
        )
    except device_service.DeviceNotFoundError as exc:
        raise _not_found(device_id) from exc
    return DeviceResponse.from_device(
        device, stale_after_seconds=settings.device_heartbeat_stale_after_seconds
    )
