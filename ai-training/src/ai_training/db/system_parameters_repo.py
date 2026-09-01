"""Raw-SQL read of backend-owned `system_parameters` (the "System Parameter"
admin menu, `backend/app/models/system_parameter.py`).

Read-only from this side — ai-training's worker never writes this table,
only ADMIN via the backend API does. Takes a DB-API `Cursor`-shaped object,
same convention as every other module in this package (see
`ai_training.db.enrollment_repo` module docstring), so tests pass a mocked
cursor, never a real Postgres connection.
"""

from __future__ import annotations

import json
from typing import Any

from ai_training.db.enrollment_repo import Cursor

ENROLLMENT_QUALITY_KEY = "enrollment_capture_quality"


def get_enrollment_quality_override(cursor: Cursor) -> dict[str, Any] | None:
    """The `enrollment_capture_quality` row's `value` jsonb, or `None` if an
    ADMIN has never saved one (the caller falls back to `QCSettings`'
    env-driven defaults in that case — see
    `ai_training.quality.pipeline.resolve_qc_settings`)."""
    cursor.execute(
        "SELECT value FROM system_parameters WHERE key = %s", (ENROLLMENT_QUALITY_KEY,)
    )
    row = cursor.fetchone()
    if row is None:
        return None
    value = row[0]
    # Most DB-API drivers (psycopg3 incl.) decode jsonb to a dict natively,
    # but a mocked test cursor (or a driver without the adapter registered)
    # may hand back the raw JSON text instead -- handle both.
    if isinstance(value, str):
        value = json.loads(value)
    return value
