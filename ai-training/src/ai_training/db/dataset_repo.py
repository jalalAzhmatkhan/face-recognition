"""Raw-SQL query for TR-04 dataset-snapshot candidates.

Finds FINALIZED `media_objects` belonging to ENROLLED `enrollment_sessions`
- the training-snapshot candidate pool (FSD-AI FR-TRN-01, TR-04). Takes a
DB-API `Cursor`-shaped object (see `ai_training.db.enrollment_repo.Cursor`)
so tests pass a mocked cursor, never a real Postgres connection - same
convention as `enrollment_repo.py`/`embedding_repo.py` (TR-02/TR-03).
"""

from __future__ import annotations

from dataclasses import dataclass

from ai_training.db.enrollment_repo import Cursor

# Filter keys `find_enrolled_media()`/`build_snapshot()` understand. An
# unrecognized key is a hard error (ValueError) rather than a silently
# ignored no-op filter - a typo'd `--filter` should fail loudly, not build
# a snapshot from an unintentionally unfiltered dataset.
SUPPORTED_FILTER_KEYS = frozenset({"external_ref", "created_after", "created_before", "kind"})


@dataclass(frozen=True)
class MediaRecord:
    """One FINALIZED media object from an ENROLLED enrollment session."""

    user_id: str
    session_id: str
    kind: str
    s3_bucket: str
    s3_key: str


def find_enrolled_media(cursor: Cursor, filters: dict[str, str] | None = None) -> list[MediaRecord]:
    """Query FINALIZED `media_objects` for ENROLLED `enrollment_sessions`.

    Supported `filters` keys (see `SUPPORTED_FILTER_KEYS`):
      - ``external_ref``: exact match against `users.external_ref` (joined
        through `enrollment_sessions.user_id -> users.id`).
      - ``created_after`` / ``created_before``: ISO-8601 timestamp bounds on
        `media_objects.created_at` (inclusive / exclusive respectively).
      - ``kind``: exact match against `media_objects.kind`
        (``'photo' | 'video' | 'event_frame'``).

    Raises `ValueError` on an unrecognized filter key.
    """
    filters = filters or {}
    unknown = set(filters) - SUPPORTED_FILTER_KEYS
    if unknown:
        raise ValueError(f"unsupported filter key(s): {sorted(unknown)}")

    query = (
        "SELECT es.user_id, mo.session_id, mo.kind, mo.s3_bucket, mo.s3_key "
        "FROM media_objects mo "
        "JOIN enrollment_sessions es ON es.id = mo.session_id "
        "JOIN users u ON u.id = es.user_id "
        "WHERE mo.status = 'FINALIZED' AND es.state = 'ENROLLED'"
    )
    params: list[str] = []
    if "external_ref" in filters:
        query += " AND u.external_ref = %s"
        params.append(filters["external_ref"])
    if "kind" in filters:
        query += " AND mo.kind = %s"
        params.append(filters["kind"])
    if "created_after" in filters:
        query += " AND mo.created_at >= %s"
        params.append(filters["created_after"])
    if "created_before" in filters:
        query += " AND mo.created_at < %s"
        params.append(filters["created_before"])
    query += " ORDER BY mo.created_at ASC"

    cursor.execute(query, tuple(params))
    rows = cursor.fetchall()
    # psycopg returns native `uuid.UUID` objects for uuid columns (mocked
    # test cursors return plain strings, which is why this only surfaced
    # live against real Postgres): coerce to `str` here, at the DB
    # boundary, so every downstream consumer (MediaEntry, the JSON
    # manifest) can rely on `user_id`/`session_id` genuinely being str
    # despite this dataclass's field annotation not being runtime-checked.
    return [
        MediaRecord(
            user_id=str(row[0]),
            session_id=str(row[1]),
            kind=row[2],
            s3_bucket=row[3],
            s3_key=row[4],
        )
        for row in rows
    ]
