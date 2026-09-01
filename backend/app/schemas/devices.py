"""Request/response contracts for `{API_V1_PREFIX}/devices/*` (BE-09, FR-USR-04)."""

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.device import Device
from app.models.enums import DeviceClass, DeviceStatus

# EC-BE-01 (TSD-edge-cases.md D-8): canonical `commissioning_checklist`
# field set. The DB column (app/models/device.py) is a loose jsonb blob on
# purpose, so this is documentation/convention rather than an enforced
# sub-model — kept here (not validated field-by-field) until
# `documentation/operations/camera-placement-guide.md` (EC-OPS-01) exists
# and either confirms this shape or requires reconciling with it:
#   camera_height_m: float | None        — target 1.5-1.6m (KRITIS absensi)
#   fill_light_installed: bool | None
#   backlight_avoided: bool | None       — camera not facing windows/backlight
#   wdr_hdr_enabled: bool | None
#   ae_lock_on_face: bool | None
#   shutter_speed_ok: bool | None        — target >= 1/250s
#   stopping_point_marked: bool | None   — a marked stop point, not a corridor
#   attendance_zone_drawn: bool | None   — only meaningful for device_class=attendance
#   commissioned_by: str | None
#   commissioned_at: str | None          — ISO 8601
#   notes: str | None


class DeviceCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    door_group: str = Field(..., min_length=1, max_length=255)
    # EC-BE-01: optional so existing callers (frontend device-registration
    # form, QA fixtures, etc.) keep working unchanged; defaults to
    # `unknown` server-side (see app/services/device_service.py), matching
    # the column's own default for devices created before this field
    # existed.
    device_class: DeviceClass | None = None
    commissioning_checklist: dict[str, Any] | None = None


class DeviceUpdateRequest(BaseModel):
    """All fields optional — PATCH semantics (mirrors UserUpdateRequest):
    only fields explicitly present in the request body are applied."""

    name: str | None = Field(None, min_length=1, max_length=255)
    door_group: str | None = Field(None, min_length=1, max_length=255)
    status: DeviceStatus | None = None
    device_class: DeviceClass | None = None
    commissioning_checklist: dict[str, Any] | None = None


class DeviceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    door_group: str
    status: DeviceStatus
    last_heartbeat_at: datetime | None
    credential_rotated_at: datetime | None
    device_class: DeviceClass
    commissioning_checklist: dict[str, Any] | None
    # v1 simplification (see Settings.device_heartbeat_stale_after_seconds):
    # there is no scheduled job yet to flip a silent device's `status` row
    # to OFFLINE on its own, so this computed field surfaces staleness at
    # read time without needing one. `None` status stays authoritative for
    # DISABLED devices (is_stale is meaningless there).
    is_stale: bool

    @classmethod
    def from_device(cls, device: Device, *, stale_after_seconds: int) -> "DeviceResponse":
        is_stale = _is_stale(device, stale_after_seconds=stale_after_seconds)
        return cls(
            id=device.id,
            name=device.name,
            door_group=device.door_group,
            status=device.status,
            last_heartbeat_at=device.last_heartbeat_at,
            credential_rotated_at=device.credential_rotated_at,
            # `device.device_class` is a DB-level default (server_default
            # + Core `default=`, see app/models/device.py) rather than a
            # Python-instrumented one, so an in-memory `Device(...)` built
            # without it explicitly (e.g. a fake repository in tests, or
            # any pre-EC-BE-01 construction site) reads back as `None`
            # until an actual flush/refresh applies the default. Coalesce
            # here so the response contract's `device_class` stays the
            # non-optional value the column is guaranteed to hold once
            # persisted.
            device_class=device.device_class or DeviceClass.UNKNOWN,
            commissioning_checklist=device.commissioning_checklist,
            is_stale=is_stale,
        )


def _is_stale(device: Device, *, stale_after_seconds: int) -> bool:
    if device.status == DeviceStatus.DISABLED:
        return False
    if device.last_heartbeat_at is None:
        return True
    age = datetime.now(UTC) - device.last_heartbeat_at
    return age.total_seconds() > stale_after_seconds


class DeviceListResponse(BaseModel):
    items: list[DeviceResponse]
    total: int
    limit: int
    offset: int


class DeviceCredentialIssuedResponse(DeviceResponse):
    """Response for `POST /devices` and `POST /devices/{id}/rotate-credential`.

    `credential` is the plaintext device bearer token
    (`<credential_id>.<secret>`) — returned exactly once. It is never
    persisted or logged anywhere; if lost, the only recovery is rotating
    the credential again (which invalidates this one)."""

    credential: str

    @classmethod
    def from_issued(
        cls, device: Device, *, credential: str, stale_after_seconds: int
    ) -> "DeviceCredentialIssuedResponse":
        base = DeviceResponse.from_device(device, stale_after_seconds=stale_after_seconds)
        return cls(**base.model_dump(), credential=credential)


class HeartbeatResponse(BaseModel):
    id: uuid.UUID
    status: DeviceStatus
    last_heartbeat_at: datetime | None
