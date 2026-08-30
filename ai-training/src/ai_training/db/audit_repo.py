"""Raw-SQL `audit_logs` insert (NFR-SEC-05: append-only — this module never
issues UPDATE/DELETE against `audit_logs`, matching the discipline
`backend/app/models/audit_log.py` documents at the ORM layer)."""

from __future__ import annotations

import json
import uuid
from typing import Any

from ai_training.db.enrollment_repo import Cursor


def insert_audit_log(
    cursor: Cursor,
    *,
    actor: str,
    action: str,
    entity: str,
    payload: dict[str, Any] | None = None,
) -> None:
    payload_json = json.dumps(payload) if payload is not None else None
    cursor.execute(
        "INSERT INTO audit_logs (id, actor, action, entity, payload) VALUES (%s, %s, %s, %s, %s)",
        (str(uuid.uuid4()), actor, action, entity, payload_json),
    )
