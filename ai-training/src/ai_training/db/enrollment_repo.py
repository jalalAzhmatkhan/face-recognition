"""Raw-SQL `enrollment_sessions`/`media_objects` access (TR-02/TR-03).

**State-transition approach (per task instructions — ai-training cannot
import `backend/app/services/enrollment_state_machine.py`)**: rather than
re-encoding the full state machine, `guarded_transition` implements the
one idiom that actually matters for correctness/idempotency — a "guarded
UPDATE" whose `WHERE` clause asserts the row is still in the expected
*current* state. This is the SQL-level expression of the exact same
pattern `backend/app/worker/tasks.py` uses at the ORM level (check current
state before writing, no-op a duplicate delivery that arrives after the
state already moved on). `ai_training.worker.tasks` only ever drives the
narrow slice of edges it needs
(`QC_RUNNING -> QC_PASSED|REJECTED_QUALITY`, `QC_PASSED -> EMBEDDING`,
`EMBEDDING -> ENROLLED`); it does not attempt to be a general-purpose state
machine.

All functions take a DB-API `Cursor`-shaped object so tests can pass a
`unittest.mock.MagicMock()` instead of a real Postgres connection (see
`tests/test_worker_task_idempotency.py` / `tests/test_db_repo.py`).
"""

from __future__ import annotations

import json
from typing import Any, Protocol


class Cursor(Protocol):
    def execute(self, query: str, params: tuple[Any, ...] = ()) -> Any: ...
    def fetchone(self) -> tuple[Any, ...] | None: ...
    rowcount: int


def get_state(cursor: Cursor, session_id: str) -> str | None:
    cursor.execute("SELECT state FROM enrollment_sessions WHERE id = %s", (session_id,))
    row = cursor.fetchone()
    return row[0] if row else None


def get_user_id(cursor: Cursor, session_id: str) -> str | None:
    cursor.execute("SELECT user_id FROM enrollment_sessions WHERE id = %s", (session_id,))
    row = cursor.fetchone()
    return row[0] if row else None


def guarded_transition(
    cursor: Cursor,
    session_id: str,
    *,
    expected_state: str,
    new_state: str,
    qc_report: dict[str, Any] | None = None,
) -> bool:
    """`UPDATE ... SET state = new_state [, qc_report = ...] WHERE id = ...
    AND state = expected_state`.

    Returns `True` iff exactly one row was updated. Zero rows means either
    the session doesn't exist or (far more commonly, given `get_state` is
    always checked first) a race/duplicate job delivery already moved the
    session past `expected_state` — the caller treats that as a no-op, not
    an error. This return value IS the idempotency check.
    """
    if qc_report is not None:
        cursor.execute(
            "UPDATE enrollment_sessions SET state = %s, qc_report = %s, updated_at = now() "
            "WHERE id = %s AND state = %s",
            (new_state, json.dumps(qc_report), session_id, expected_state),
        )
    else:
        cursor.execute(
            "UPDATE enrollment_sessions SET state = %s, updated_at = now() "
            "WHERE id = %s AND state = %s",
            (new_state, session_id, expected_state),
        )
    return cursor.rowcount == 1


def get_latest_finalized_video(cursor: Cursor, session_id: str) -> tuple[str, str] | None:
    """Return `(s3_bucket, s3_key)` of the most recent FINALIZED video
    media object for this session, or `None` if there isn't one yet."""
    cursor.execute(
        "SELECT s3_bucket, s3_key FROM media_objects "
        "WHERE session_id = %s AND kind = 'video' AND status = 'FINALIZED' "
        "ORDER BY created_at DESC LIMIT 1",
        (session_id,),
    )
    row = cursor.fetchone()
    return (row[0], row[1]) if row else None
