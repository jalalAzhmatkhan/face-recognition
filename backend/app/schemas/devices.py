"""Request/response contracts for `{API_V1_PREFIX}/devices/*` (BE-09, FR-USR-04)."""

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.device import Device
from app.models.enums import DeviceStatus


class DeviceCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    door_group: str = Field(..., min_length=1, max_length=255)


class DeviceUpdateRequest(BaseModel):
    """All fields optional — PATCH semantics (mirrors UserUpdateRequest):
    only fields explicitly present in the request body are applied."""

    name: str | None = Field(None, min_length=1, max_length=255)
    door_group: str | None = Field(None, min_length=1, max_length=255)
    status: DeviceStatus | None = None


class DeviceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    door_group: str
    status: DeviceStatus
    last_heartbeat_at: datetime | None
    credential_rotated_at: datetime | None
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
