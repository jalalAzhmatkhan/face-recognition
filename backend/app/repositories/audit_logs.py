"""Repository for `audit_logs` (BE-04, NFR-SEC-05).

INSERT/SELECT only — see app/models/audit_log.py docstring: no UPDATE/DELETE
is ever exposed here, matching the append-only DB-level guarantee.
"""

from typing import Any

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


class AuditLogRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def record(
        self,
        *,
        actor: str,
        action: str,
        entity: str,
        payload: dict[str, Any] | None = None,
    ) -> AuditLog:
        entry = AuditLog(actor=actor, action=action, entity=entity, payload=payload)
        self._session.add(entry)
        self._session.commit()
        self._session.refresh(entry)
        return entry
