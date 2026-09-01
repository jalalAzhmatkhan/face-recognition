"""Repository for `system_parameters` (System Parameter admin menu)."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.system_parameter import SystemParameter


class SystemParameterRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, key: str) -> SystemParameter | None:
        return self._session.get(SystemParameter, key)

    def upsert(self, key: str, value: dict, *, updated_by: uuid.UUID) -> SystemParameter:
        param = self._session.get(SystemParameter, key)
        if param is None:
            param = SystemParameter(key=key, value=value, updated_by=updated_by)
            self._session.add(param)
        else:
            param.value = value
            param.updated_by = updated_by
        self._session.commit()
        self._session.refresh(param)
        return param
