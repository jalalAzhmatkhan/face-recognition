"""Device registry business logic (BE-09, FR-USR-04, NFR-SEC-04).

Layering per app/main.py docstring: routers (HTTP) -> services (business
logic) -> repositories (data access). This module owns:
  - issuing/rotating per-device token credentials (plaintext returned to the
    caller exactly once — never persisted, never logged, never included in
    an audit payload),
  - verifying a presented device bearer token against the stored Argon2id
    hash (used by app/dependencies/device_auth.py),
  - recording heartbeats (-> status ONLINE),
  - writing an `audit_logs` entry for register/rotate/update/disable, same
    pattern as app/services/user_service.py.
"""

import uuid
from datetime import UTC, datetime
from typing import Any, NamedTuple

from app.core.security import (
    generate_device_credential,
    hash_secret,
    parse_device_token,
    verify_secret,
)
from app.models.device import Device
from app.models.enums import DeviceStatus
from app.repositories.audit_logs import AuditLogRepository
from app.repositories.devices import DeviceRepository


class DeviceNotFoundError(Exception):
    """No device exists with the given id."""


class InvalidDeviceCredentialError(Exception):
    """Presented device bearer token does not match any known, live credential.

    Deliberately raised for every failure mode (malformed token, unknown
    credential_id, wrong secret) so a caller can never distinguish "no such
    device" from "wrong secret" from the response (NFR-SEC-04: no info leak,
    same principle as app/core/security.py's `verify_password`).
    """


class DeviceDisabledError(Exception):
    """Credential is valid but the device has been administratively DISABLED."""

    def __init__(self, device: Device) -> None:
        self.device = device
        super().__init__(str(device.id))


class IssuedCredential(NamedTuple):
    device: Device
    plaintext_token: str


def get_device(repo: DeviceRepository, device_id: uuid.UUID) -> Device:
    device = repo.get(device_id)
    if device is None:
        raise DeviceNotFoundError(str(device_id))
    return device


def list_devices(
    repo: DeviceRepository,
    *,
    status: DeviceStatus | None = None,
    door_group: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Device], int]:
    items = repo.list(status=status, door_group=door_group, limit=limit, offset=offset)
    total = repo.count(status=status, door_group=door_group)
    return items, total


def register_device(
    repo: DeviceRepository,
    audit_repo: AuditLogRepository,
    *,
    name: str,
    door_group: str,
    actor: str,
) -> IssuedCredential:
    """Create a new device row with a freshly issued credential.

    The plaintext token is returned to the caller (only) as part of
    `IssuedCredential` — it is never written anywhere, including the audit
    log payload (which records only non-secret metadata).
    """
    credential_id, plaintext_secret, plaintext_token = generate_device_credential()
    now = datetime.now(UTC)

    device = Device(
        name=name,
        door_group=door_group,
        auth_credential_ref=credential_id,
        credential_hash=hash_secret(plaintext_secret),
        credential_rotated_at=now,
        status=DeviceStatus.OFFLINE,
    )
    device = repo.create(device)

    audit_repo.record(
        actor=actor,
        action="device.register",
        entity=f"device:{device.id}",
        payload={"name": name, "door_group": door_group},
    )
    return IssuedCredential(device=device, plaintext_token=plaintext_token)


def rotate_credential(
    repo: DeviceRepository,
    audit_repo: AuditLogRepository,
    *,
    device_id: uuid.UUID,
    actor: str,
) -> IssuedCredential:
    """Invalidate the device's current credential and issue a new one.

    Overwriting `auth_credential_ref`/`credential_hash` is itself the
    invalidation — the old token's credential_id no longer resolves to this
    (or any) device once replaced, so any request bearing the old token
    immediately fails device authentication.
    """
    device = repo.get(device_id)
    if device is None:
        raise DeviceNotFoundError(str(device_id))

    credential_id, plaintext_secret, plaintext_token = generate_device_credential()
    device.auth_credential_ref = credential_id
    device.credential_hash = hash_secret(plaintext_secret)
    device.credential_rotated_at = datetime.now(UTC)
    device = repo.update(device)

    audit_repo.record(
        actor=actor,
        action="device.rotate_credential",
        entity=f"device:{device.id}",
        payload={},
    )
    return IssuedCredential(device=device, plaintext_token=plaintext_token)


def authenticate_device(repo: DeviceRepository, *, token: str) -> Device:
    """Resolve+verify a presented bearer token into its owning `Device`.

    Raises `InvalidDeviceCredentialError` for any bad-token reason, or
    `DeviceDisabledError` when the credential itself checks out but the
    device is administratively DISABLED (a distinct, non-secret-leaking
    condition worth a different HTTP status at the dependency layer).
    """
    parsed = parse_device_token(token)
    if parsed is None:
        raise InvalidDeviceCredentialError("Malformed device token")
    credential_id, secret = parsed

    device = repo.get_by_credential_id(credential_id)
    if device is None or device.credential_hash is None:
        raise InvalidDeviceCredentialError("Unknown device credential")

    if not verify_secret(secret, device.credential_hash):
        raise InvalidDeviceCredentialError("Invalid device credential")

    if device.status == DeviceStatus.DISABLED:
        raise DeviceDisabledError(device)

    return device


def record_heartbeat(repo: DeviceRepository, *, device: Device) -> Device:
    """Update `last_heartbeat_at` and mark the device ONLINE (FR-USR-04).

    No audit entry: heartbeats are high-frequency, routine device traffic,
    not an administrative action — audit_logs stays reserved for
    staff-driven changes (register/rotate/update/disable), matching how
    user_service treats reads vs. status-changing writes.
    """
    device.last_heartbeat_at = datetime.now(UTC)
    device.status = DeviceStatus.ONLINE
    return repo.update(device)


def _serialize(value: Any) -> Any:
    return value.value if isinstance(value, DeviceStatus) else value


def update_device(
    repo: DeviceRepository,
    audit_repo: AuditLogRepository,
    *,
    device_id: uuid.UUID,
    updates: dict[str, Any],
    actor: str,
) -> Device:
    """`updates` MUST come from `DeviceUpdateRequest.model_dump(exclude_unset=True)`
    (mirrors app/services/user_service.py's `update_user`)."""
    device = repo.get(device_id)
    if device is None:
        raise DeviceNotFoundError(str(device_id))

    if "name" in updates:
        device.name = updates["name"]
    if "door_group" in updates:
        device.door_group = updates["door_group"]
    if "status" in updates:
        device.status = updates["status"]

    device = repo.update(device)

    audit_repo.record(
        actor=actor,
        action="device.update",
        entity=f"device:{device.id}",
        payload={k: _serialize(v) for k, v in updates.items()},
    )
    return device


def disable_device(
    repo: DeviceRepository,
    audit_repo: AuditLogRepository,
    *,
    device_id: uuid.UUID,
    actor: str,
) -> Device:
    """Used by `DELETE /devices/{id}` — never hard-deletes a device (the row
    is still referenced by historical `access_events`), so "delete" is
    defined as a transition to DISABLED. Mirrors
    `user_service.offboard_user`'s DELETE-as-status-transition alias."""
    return update_device(
        repo,
        audit_repo,
        device_id=device_id,
        updates={"status": DeviceStatus.DISABLED},
        actor=actor,
    )
