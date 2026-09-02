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
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


class Cursor(Protocol):
    def execute(self, query: str, params: tuple[Any, ...] = ()) -> Any: ...
    def fetchone(self) -> tuple[Any, ...] | None: ...
    def fetchall(self) -> list[tuple[Any, ...]]: ...
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


def list_enrolled_sessions(cursor: Cursor) -> list[tuple[str, str]]:
    """Return `(session_id, user_id)` for every session currently `ENROLLED`
    (TR-08, FR-TRN-06). This is the universe the gallery re-embed job walks
    — a session that never reached ENROLLED never had gallery embeddings to
    begin with, and REVOKED/CANCELLED sessions must not be re-added to the
    gallery (their embeddings were already hard-deleted by BE-08's
    revocation cleanup, or never existed).

    Explicit `str(...)` coercion: found live — psycopg returns native
    `uuid.UUID` objects for UUID columns, not strings, which crashed
    `QCReport` pydantic validation (it requires `session_id: str`) the
    first time this ran against real Postgres. Same class of bug as the
    UUID-coercion fix in `dataset_repo.py` (TR-04/05) — not caught by any
    mocked test because a `FakeCursor` naturally hands back whatever
    Python type the test itself put in.
    """
    cursor.execute("SELECT id, user_id FROM enrollment_sessions WHERE state = 'ENROLLED'")
    return [(str(row[0]), str(row[1])) for row in cursor.fetchall()]


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


def get_frontal_photo(cursor: Cursor, session_id: str) -> tuple[str, str] | None:
    """Return `(s3_bucket, s3_key)` of this session's FRONTAL photo -- the
    EARLIEST FINALIZED `kind = 'photo'` row (`photo_1.jpg`, taken on the
    wizard's preflight step before the sweep starts) -- or `None`.

    Used as the NEUTRAL POSE REFERENCE for QC: the subject is looking
    straight at the camera in this shot by construction, so estimating its
    pose gives the per-subject baseline every sweep frame is measured
    against. See `ai_training.quality.pipeline.apply_neutral_offset` for why
    that baseline is needed at all.

    `clock_position IS NULL` excludes the per-position sweep frames (which
    are also `kind = 'photo'`, migration `e4b9d2f6a8c3`) -- those are the
    poses being MEASURED, so using one as the baseline would cancel out the
    very movement QC is checking for. Legacy rows predate the column and are
    NULL, so they still match.

    `ORDER BY created_at ASC` (not DESC like the video lookups above): a
    retaken photo appends a NEW row (`photo_2.jpg`, ...) rather than
    replacing the first, and it is the earliest one that is the frontal
    shot the presign flow numbers `photo_1`.
    """
    cursor.execute(
        "SELECT s3_bucket, s3_key FROM media_objects "
        "WHERE session_id = %s AND kind = 'photo' AND status = 'FINALIZED' "
        "AND clock_position IS NULL "
        "ORDER BY created_at ASC LIMIT 1",
        (session_id,),
    )
    row = cursor.fetchone()
    return (row[0], row[1]) if row else None


@dataclass(frozen=True)
class VideoMedia:
    """One FINALIZED video `media_objects` row, with its retention info
    (D-4.5 backfill, TSD-edge-cases.md D-4.5/ASM-10) -- a superset of what
    `get_latest_finalized_video` returns, added separately rather than
    changing that function's signature/callers (TR-08's
    `run_gallery_reembed_job_core` and its tests depend on the 2-tuple
    shape as-is)."""

    bucket: str
    key: str
    retention_expires_at: datetime | None


def get_latest_finalized_video_with_retention(cursor: Cursor, session_id: str) -> VideoMedia | None:
    """Like `get_latest_finalized_video`, plus `retention_expires_at`
    (D-4.5's "prasyarat: media masih dalam retensi 90 hari" check).

    `None` here covers BOTH "this session never had a FINALIZED video" and
    "it had one but `retention_service.purge_expired_media` (BE-14) already
    hard-deleted the row" -- purge deletes the `media_objects` row entirely,
    so there is no distinguishing tombstone left behind. For a session that
    is `ENROLLED` (the only sessions D-4.5 iterates -- see
    `list_enrolled_sessions`), reaching ENROLLED is only possible after a
    FINALIZED video existed at some point, so for THIS caller specifically,
    `None` is treated as "media lewat retensi" (the legacy fallback D-4.5's
    caller applies), not as a data-integrity error.

    A row that still exists but whose `retention_expires_at` has already
    passed (the purge job runs hourly, not instantly) is returned as-is
    (not filtered out here) -- the caller checks `retention_expires_at`
    against `now()` itself so it can log/count that case distinctly from
    "row genuinely gone".
    """
    cursor.execute(
        "SELECT s3_bucket, s3_key, retention_expires_at FROM media_objects "
        "WHERE session_id = %s AND kind = 'video' AND status = 'FINALIZED' "
        "ORDER BY created_at DESC LIMIT 1",
        (session_id,),
    )
    row = cursor.fetchone()
    return VideoMedia(bucket=row[0], key=row[1], retention_expires_at=row[2]) if row else None


def mark_user_reenroll_due(cursor: Cursor, *, user_id: str, reason: str) -> bool:
    """D-4.5's permanent fallback (TSD-edge-cases.md D-4.5/A-5): flag a
    legacy user whose enrollment video has passed retention (ASM-10, so it
    can never be backfilled) as needing re-enrollment, via EC-BE-05's
    `reenroll_due` mechanism (`features/ec-be-05-reenroll-due-policy`,
    migration `d8e1f3a6c2b5`).

    **Cross-service integration, confirmed live with EC-BE-05's author**:
    `users.reenroll_due` (bool) / `users.reenroll_due_reason` (free-text-ish
    short code, deliberately not an enum) / `users.reenroll_due_marked_at`
    (set once, at first flagging). Written via direct SQL, same convention
    as every other cross-service write ai-training makes (`face_embeddings`,
    `enrollment_sessions.state`, `training_jobs`, `audit_logs` -- all direct
    SQL against tables backend's migrations grant to the
    `ai_training_embeddings_write` role, never an HTTP call to backend).

    **Idempotency contract (EC-BE-05's, shared with its own
    `reenroll_due_service.evaluate_reenroll_due` producer)**: if
    `reenroll_due` is already `true` for this user, this does NOT overwrite
    `reenroll_due_reason`/`reenroll_due_marked_at` and does NOT write a
    duplicate audit entry -- first-to-flag wins, so two independent
    producers (this backfill job and EC-BE-05's own age/score-based job)
    never clobber each other's record. Returns `True` iff this call is the
    one that actually flipped the flag false->true (the caller uses this to
    decide whether to write the shared `user.reenroll_due_marked` audit
    entry -- see EC-BE-05's payload shape, which this does not need to
    match exactly beyond the `action` name, so ops can query both producers
    with one `WHERE action = 'user.reenroll_due_marked'`); `False` means
    "already flagged by someone, this call was a no-op".

    Deliberately does not catch/suppress a schema-mismatch error itself --
    `run_backfill_masked_templates_job_core`'s per-session try/except is
    what turns that into a `failed`-counted session instead of aborting the
    whole batch, exactly like every other per-session failure mode there.
    """
    cursor.execute("SELECT reenroll_due FROM users WHERE id = %s", (user_id,))
    row = cursor.fetchone()
    if row is not None and row[0]:
        return False
    cursor.execute(
        "UPDATE users SET reenroll_due = true, reenroll_due_reason = %s, "
        "reenroll_due_marked_at = now() WHERE id = %s",
        (reason, user_id),
    )
    return True
