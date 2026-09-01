"""devices — access-control door devices (TSD §4, FR-USR-04)."""

from datetime import datetime

from sqlalchemy import DateTime, Enum, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import DeviceClass, DeviceStatus
from app.models.mixins import UUIDPKMixin


class Device(UUIDPKMixin, Base):
    __tablename__ = "devices"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    door_group: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # Reference/handle to the credential material (mTLS cert id, token id, ...); the
    # actual secret material never lives in this table.
    #
    # BE-09: for the v1 token-based credential scheme (see
    # app/services/device_service.py), this holds the public, non-secret
    # "credential id" half of the issued token (`<credential_id>.<secret>`) —
    # used to look a device up by presented token before verifying the
    # secret half against `credential_hash`. It is unique per device so a
    # rotated/registered credential id can never collide with another
    # device's.
    auth_credential_ref: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    # Argon2id hash of the credential secret half (BE-09). Mirrors
    # `staff_accounts.password_hash` (app/core/security.py) — never store the
    # plaintext secret; it is returned to the caller exactly once at
    # registration/rotation time and is unrecoverable afterwards.
    credential_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # When the credential currently on file was issued/last rotated (BE-09).
    # Nullable because devices created before this column existed (there are
    # none in practice yet, since BE-09 ships before any device is
    # registered) would otherwise have no value.
    credential_rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[DeviceStatus] = mapped_column(
        Enum(DeviceStatus, name="device_status", native_enum=True),
        nullable=False,
        default=DeviceStatus.OFFLINE,
        server_default=DeviceStatus.OFFLINE.value,
    )
    # EC-BE-01 (TSD-edge-cases.md D-5/D-10): drives per-device-class
    # recognition-policy resolution (a later task) and is denormalized onto
    # `access_events.device_class` at ingest time (see
    # app/services/access_event_service.py) so funnel-logging queries never
    # need to join `devices`. NOT NULL + `unknown` default so every existing
    # device registered before this column existed gets a safe, non-error
    # classification rather than NULL.
    device_class: Mapped[DeviceClass] = mapped_column(
        Enum(
            DeviceClass,
            name="device_class",
            native_enum=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=DeviceClass.UNKNOWN,
        server_default=DeviceClass.UNKNOWN.value,
    )
    # EC-BE-01 (TSD-edge-cases.md D-8): operator-filled commissioning
    # checklist (camera height, fill-light, WDR/HDR+AE-lock, shutter speed,
    # stopping point, attendance-zone drawing — see D-8). NULL means "not
    # commissioned yet". Schema is intentionally a loose jsonb blob (not a
    # DB-level shape constraint) — see app/schemas/devices.py for the
    # canonical field set, which MUST be kept in sync with whatever
    # `documentation/operations/camera-placement-guide.md` (EC-OPS-01)
    # ends up defining once that document exists.
    commissioning_checklist: Mapped[dict | None] = mapped_column(JSONB)
