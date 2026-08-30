"""devices — access-control door devices (TSD §4, FR-USR-04)."""

from datetime import datetime

from sqlalchemy import DateTime, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import DeviceStatus
from app.models.mixins import UUIDPKMixin


class Device(UUIDPKMixin, Base):
    __tablename__ = "devices"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    door_group: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # Reference/handle to the credential material (mTLS cert id, token id, ...); the
    # actual secret material never lives in this table.
    auth_credential_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[DeviceStatus] = mapped_column(
        Enum(DeviceStatus, name="device_status", native_enum=True),
        nullable=False,
        default=DeviceStatus.OFFLINE,
        server_default=DeviceStatus.OFFLINE.value,
    )
