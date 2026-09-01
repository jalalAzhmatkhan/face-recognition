"""Request/response contracts for `{API_V1_PREFIX}/devices/*` (BE-09, FR-USR-04)."""

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.device import Device
from app.models.enums import DeviceClass, DeviceStatus

# EC-BE-01 (TSD-edge-cases.md D-8): `commissioning_checklist` canonical
# shape now FINALIZED by `documentation/operations/camera-placement-guide.md`
# §5 (EC-OPS-01, not committed — gitignored like the rest of
# `documentation/operations/`). The DB column (app/models/device.py) stays a
# loose jsonb blob on purpose (no DB-level JSON Schema, per that doc's §5.5)
# — structural validation happens at this Pydantic layer instead, but is
# NOT yet implemented as a nested sub-model here (still `dict[str, Any]`);
# tracked as follow-up so EC-FE-01's form and any backend validation agree
# on the exact contract. Top-level shape (see camera-placement-guide.md §5.1
# for the full field table + §5.6 for a worked example):
#   schema_version: str                      — e.g. "1.0"
#   device_class: "access_control" | "attendance"
#   overall_status: "pending" | "passed" | "failed"
#   commissioned_at: str | None               — ISO 8601, required unless pending
#   commissioned_by_staff_id: str | None      — UUID, required unless pending
#   commissioned_by_name: str | None
#   site_notes: str | None
#   checks: list[dict]                        — one entry per checklist item,
#       each: id, category, label, applicable_device_classes, required,
#       value_type, unit?, expected_range?/expected_value?/enum_options?,
#       measured_value, status ("pass"|"fail"|"na"|None), notes,
#       checked_at, checked_by_staff_id — canonical `id` catalog is
#       camera-placement-guide.md §5.4
#   queue_zone: dict | None                   — required (non-null) only when
#       device_class == "attendance"; see §5.3 for its own field set
#       (stop_point_marked, stop_point_distance_m, single_face_zone_defined,
#       zone_shape, zone_reference_photo_s3_key, notes)
#   reverify_due_at: str | None                — ISO 8601 date/datetime


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
