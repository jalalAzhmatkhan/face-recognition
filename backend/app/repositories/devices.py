"""Repository for `devices` (BE-09, FR-USR-04).

Mirrors the minimal CRUD pattern established by `app/repositories/users.py`
— no business logic here, just data access.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.device import Device
from app.models.enums import DeviceStatus


class DeviceRepository:
    """Thin data-access wrapper around a SQLAlchemy `Session`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, device_id: uuid.UUID) -> Device | None:
        return self._session.get(Device, device_id)

    def get_by_credential_id(self, credential_id: str) -> Device | None:
        """Look a device up by the non-secret `credential_id` half of its
        issued token (stored in `auth_credential_ref`) — used by device
        authentication (see app/services/device_service.py)."""
        stmt = select(Device).where(Device.auth_credential_ref == credential_id)
        return self._session.scalars(stmt).one_or_none()

    def list(
        self,
        *,
        status: DeviceStatus | None = None,
        door_group: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Device]:
        stmt = select(Device).order_by(Device.name).limit(limit).offset(offset)
        if status is not None:
            stmt = stmt.where(Device.status == status)
        if door_group is not None:
            stmt = stmt.where(Device.door_group == door_group)
        return list(self._session.scalars(stmt))

    def count(self, *, status: DeviceStatus | None = None, door_group: str | None = None) -> int:
        stmt = select(func.count()).select_from(Device)
        if status is not None:
            stmt = stmt.where(Device.status == status)
        if door_group is not None:
            stmt = stmt.where(Device.door_group == door_group)
        return self._session.scalar(stmt) or 0

    def create(self, device: Device) -> Device:
        self._session.add(device)
        self._session.commit()
        self._session.refresh(device)
        return device

    def update(self, device: Device) -> Device:
        self._session.add(device)
        self._session.commit()
        self._session.refresh(device)
        return device
