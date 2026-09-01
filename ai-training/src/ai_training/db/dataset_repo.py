"""Raw-SQL query for TR-04/EC-TR-05 dataset-snapshot candidates.

Finds FINALIZED `media_objects` for the training-snapshot candidate pool
(FSD-AI FR-TRN-01, TR-04). Takes a DB-API `Cursor`-shaped object (see
`ai_training.db.enrollment_repo.Cursor`) so tests pass a mocked cursor,
never a real Postgres connection - same convention as
`enrollment_repo.py`/`embedding_repo.py` (TR-02/TR-03).

EC-TR-05 (TSD-edge-cases.md B-4) adds a second candidate pool alongside the
original enrollment-media one: `source=event_frame` selects door-camera
frames (`media_objects.session_id IS NULL`, see migration `b2e6f9a1c4d7`)
joined back to the `access_events` row that captured them
(`AccessEvent.frame_media_id`) so callers can filter by that decision's
`condition_flags` (masked/dark/blurry/low_res/sunglasses - EC-BE-01/D-1).
An event-frame row has no enrollment session and, for an unmatched/impostor
probe, no identity either - `MediaRecord.user_id`/`session_id` are
therefore optional (`None` for exactly this case), unlike the original
`source=enrollment` pool where both are always populated.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai_training.db.enrollment_repo import Cursor

# Condition flags EC-IN-01 logs onto `access_events.condition_flags`
# (TSD-edge-cases.md D-1). Kept as an explicit allow-list, same rationale as
# SUPPORTED_FILTER_KEYS below: a typo'd `--filter condition=drak` should
# fail loudly, not silently build an unfiltered (or wrongly empty) dataset.
SUPPORTED_CONDITION_FLAGS = frozenset({"masked", "dark", "blurry", "low_res", "sunglasses"})

SUPPORTED_SOURCES = frozenset({"enrollment", "event_frame"})

# Filter keys `find_enrolled_media()`/`build_snapshot()` understand. An
# unrecognized key is a hard error (ValueError) rather than a silently
# ignored no-op filter - a typo'd `--filter` should fail loudly, not build
# a snapshot from an unintentionally unfiltered dataset.
SUPPORTED_FILTER_KEYS = frozenset(
    {"external_ref", "created_after", "created_before", "kind", "variant", "condition", "source"}
)


@dataclass(frozen=True)
class MediaRecord:
    """One FINALIZED media object - either enrollment media (`source`
    defaults to `"enrollment"`, `user_id`/`session_id` always populated) or,
    since EC-TR-05, an EVENT_FRAME probe (`source="event_frame"`,
    `user_id`/`session_id` `None` when the frame was never matched to an
    identity / has no enrollment session)."""

    user_id: str | None
    session_id: str | None
    kind: str
    s3_bucket: str
    s3_key: str
    source: str = "enrollment"


def find_enrolled_media(cursor: Cursor, filters: dict[str, str] | None = None) -> list[MediaRecord]:
    """Query FINALIZED `media_objects` candidates for a dataset snapshot.

    Supported `filters` keys (see `SUPPORTED_FILTER_KEYS`):
      - ``external_ref``: exact match against `users.external_ref` (joined
        through `enrollment_sessions.user_id -> users.id`). Only valid for
        `source=enrollment` (the default) - an event-frame probe has no
        enrollment session to join through.
      - ``created_after`` / ``created_before``: ISO-8601 timestamp bounds on
        `media_objects.created_at` (inclusive / exclusive respectively).
      - ``kind``: exact match against `media_objects.kind`
        (``'photo' | 'video' | 'event_frame'``).
      - ``variant`` (EC-TR-05): exact match against `media_objects.variant`
        (``'default' | 'no_glasses' | 'glasses' | 'pitch_ext'``, EC-BE-02).
      - ``source`` (EC-TR-05): ``'enrollment'`` (default - the original
        TR-04 pool, ENROLLED sessions only) or ``'event_frame'`` (door-camera
        frames with no enrollment session, see module docstring).
      - ``condition`` (EC-TR-05): one of `SUPPORTED_CONDITION_FLAGS`: keeps
        only event-frame rows whose captured `access_events.condition_flags`
        has this flag truthy. Requires `source=event_frame` - condition
        flags only exist on access-event decisions, never on enrollment
        media, so combining `condition` with `source=enrollment` (or
        omitting `source`) is a `ValueError`, not a silent no-op.

    Raises `ValueError` on an unrecognized filter key/value, or an
    unsatisfiable filter combination (`condition` without
    `source=event_frame`).
    """
    filters = filters or {}
    unknown = set(filters) - SUPPORTED_FILTER_KEYS
    if unknown:
        raise ValueError(f"unsupported filter key(s): {sorted(unknown)}")

    source = filters.get("source", "enrollment")
    if source not in SUPPORTED_SOURCES:
        raise ValueError(
            f"unsupported source: {source!r} (expected one of {sorted(SUPPORTED_SOURCES)})"
        )

    if "condition" in filters:
        if source != "event_frame":
            raise ValueError("'condition' filter requires source=event_frame")
        if filters["condition"] not in SUPPORTED_CONDITION_FLAGS:
            raise ValueError(
                f"unsupported condition: {filters['condition']!r} "
                f"(expected one of {sorted(SUPPORTED_CONDITION_FLAGS)})"
            )

    if source == "event_frame":
        # `kind` is implicitly always 'event_frame' for this source, and
        # `external_ref` has nothing to join through (no enrollment
        # session) - accepting either silently would either be a no-op the
        # caller can't detect, or (worse, for `external_ref`) silently
        # ignore a filter the caller thought was narrowing the result.
        incompatible = {"kind", "external_ref"} & set(filters)
        if incompatible:
            raise ValueError(
                f"filter(s) {sorted(incompatible)} are not valid with source=event_frame"
            )

    if source == "event_frame":
        rows = _find_event_frame_media(cursor, filters)
    else:
        rows = _find_enrollment_media(cursor, filters)

    # psycopg returns native `uuid.UUID` objects for uuid columns (mocked
    # test cursors return plain strings, which is why this only surfaced
    # live against real Postgres): coerce to `str` here, at the DB
    # boundary, so every downstream consumer (MediaEntry, the JSON
    # manifest) can rely on `user_id`/`session_id` genuinely being str (or
    # None) despite this dataclass's field annotations not being
    # runtime-checked.
    return [
        MediaRecord(
            user_id=str(row[0]) if row[0] is not None else None,
            session_id=str(row[1]) if row[1] is not None else None,
            kind=row[2],
            s3_bucket=row[3],
            s3_key=row[4],
            source=source,
        )
        for row in rows
    ]


def _find_enrollment_media(cursor: Cursor, filters: dict[str, str]) -> list[tuple]:
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
    if "variant" in filters:
        query += " AND mo.variant = %s"
        params.append(filters["variant"])
    if "created_after" in filters:
        query += " AND mo.created_at >= %s"
        params.append(filters["created_after"])
    if "created_before" in filters:
        query += " AND mo.created_at < %s"
        params.append(filters["created_before"])
    query += " ORDER BY mo.created_at ASC"

    cursor.execute(query, tuple(params))
    return cursor.fetchall()


def _find_event_frame_media(cursor: Cursor, filters: dict[str, str]) -> list[tuple]:
    # LEFT JOIN, not JOIN: a media_objects row with session_id IS NULL is
    # only reliably an EVENT_FRAME once EC-IN-06-style ingestion actually
    # writes `access_events.frame_media_id` back to it (see migration
    # b2e6f9a1c4d7's docstring - no code does this yet), but the row itself
    # is still a valid, filterable event-frame candidate even before that
    # link exists; a plain JOIN would silently drop it instead of just
    # leaving `matched_user_id`/`condition_flags` NULL.
    query = (
        "SELECT ae.matched_user_id, mo.session_id, mo.kind, mo.s3_bucket, mo.s3_key "
        "FROM media_objects mo "
        "LEFT JOIN access_events ae ON ae.frame_media_id = mo.id "
        "WHERE mo.status = 'FINALIZED' AND mo.session_id IS NULL AND mo.kind = 'event_frame'"
    )
    params: list[str] = []
    if "variant" in filters:
        query += " AND mo.variant = %s"
        params.append(filters["variant"])
    if "condition" in filters:
        query += " AND (ae.condition_flags ->> %s)::boolean IS TRUE"
        params.append(filters["condition"])
    if "created_after" in filters:
        query += " AND mo.created_at >= %s"
        params.append(filters["created_after"])
    if "created_before" in filters:
        query += " AND mo.created_at < %s"
        params.append(filters["created_before"])
    query += " ORDER BY mo.created_at ASC"

    cursor.execute(query, tuple(params))
    return cursor.fetchall()
