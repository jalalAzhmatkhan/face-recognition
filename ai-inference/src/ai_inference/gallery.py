"""Raw-SQL gallery access for ``/recognize`` (IN-03, FR-INF-03).

Uses the read-only ``ai_inference_ro`` Postgres role (backend migration
``b7c4e1a2d9f0``): SELECT-only on ``models`` (find the current PRODUCTION
version) and ``face_embeddings`` (pgvector ANN search). No other table
access.

Functions take a DB-API ``Cursor``-shaped object (mirrors
``ai_training.db.enrollment_repo.Cursor``/``ai_training.db.embedding_repo``)
so this module is unit-testable with a fake cursor, no real Postgres
needed -- see ``tests/test_gallery.py``. This module does NOT import
``psycopg``/``pgvector`` at module level (only inside ``get_connection``,
which real callers use to build a cursor) so it stays importable without the
``ml`` extra installed, per this project's lazy-import convention.
"""

from __future__ import annotations

from typing import Any, Protocol


class Cursor(Protocol):
    def execute(self, query: str, params: tuple[Any, ...] = ()) -> Any: ...
    def fetchone(self) -> tuple[Any, ...] | None: ...
    def fetchall(self) -> list[tuple[Any, ...]]: ...


def get_connection(dsn: str) -> Any:
    """Open a `psycopg` (v3) connection using the `ai_inference_ro` role and
    register the `pgvector` adapter so query results for the `vector` column
    round-trip as plain Python lists/arrays. Lazy import -- requires the
    `ml` extra (`uv sync --extra ml`): psycopg[binary], pgvector.
    """
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - depends on extras
        raise RuntimeError(
            "gallery.get_connection requires the 'ml' extra (uv sync --extra ml): "
            "psycopg[binary] (pulled in transitively via the ai-training path dependency)."
        ) from exc

    conn = psycopg.connect(dsn)
    try:
        from pgvector.psycopg import register_vector

        register_vector(conn)
    except ImportError:  # pragma: no cover - depends on extras
        pass
    return conn


def get_current_production_model_version(cursor: Cursor) -> str | None:
    """The `models.version` currently `stage = 'PRODUCTION'` AND
    `model_kind = 'embedder'`, or `None` if there isn't one.

    Fail-secure contract (IN-03 task brief): callers MUST treat `None` as
    "no gallery search is possible right now" and return `UNKNOWN` for every
    frame, never a 500 -- there being no PRODUCTION model is an expected,
    not exceptional, operational state (e.g. before the first promotion).

    The `model_kind = 'embedder'` filter is EC-BE-06 (TSD-EC B-3's registry
    split): once a `liveness`-kind model can ALSO be `stage = 'PRODUCTION'`
    at the same time as an embedder (each kind has its own independent
    PRODUCTION slot -- `app/services/training_service.py::promote_model`
    scopes its retire-old-PRODUCTION step by the candidate's own kind), a
    query with no kind filter would risk this function returning a
    LIVENESS model's version string as if it were the embedder's -- exactly
    the "compare a query embedding against a gallery re-embedded under a
    different model" hazard this module's own docstring warns about, just
    caused by kind confusion instead of a stale cache. This is no longer
    the "should not happen" multi-PRODUCTION-row case the tie-break below
    was written for; it is an expected steady state once liveness models
    exist at all.

    If more than one row is somehow BOTH `stage = 'PRODUCTION'` AND
    `model_kind = 'embedder'` (should not happen -- IN-07's atomic switch is
    meant to prevent it, but this module does not assume that invariant
    holds), the most recently promoted one wins
    (`ORDER BY promoted_at DESC NULLS LAST`), which is the least surprising
    tie-break and does not require a schema change here to enforce at the
    DB level.
    """
    cursor.execute(
        "SELECT version FROM models WHERE stage = 'PRODUCTION' AND model_kind = 'embedder' "
        "ORDER BY promoted_at DESC NULLS LAST LIMIT 1"
    )
    row = cursor.fetchone()
    return row[0] if row else None


def search_top_k(
    cursor: Cursor,
    *,
    embedding: list[float],
    model_version: str,
    k: int,
    masked: bool | None = None,
) -> list[tuple[str, float]]:
    """Top-`k` `(user_id, similarity)` pairs for `model_version`'s gallery
    templates, ordered by similarity DESCENDING (best match first).

    Raw rows here are per-TEMPLATE, not per-user (a user has up to ~13
    templates, one per pose bucket) -- max-fusion collapse to one score per
    user happens in `ai_inference.pipeline.recognize`, not here, so this
    function stays a thin, directly-testable SQL wrapper.

    pgvector's `<=>` operator is COSINE DISTANCE (`1 - cosine_similarity`),
    ascending = most similar first; this converts to similarity
    (`1 - distance`) before returning so callers only ever deal with
    similarity, matching `settings.similarity_threshold`'s convention.

    **`::vector` cast, found live**: `register_vector(conn)` in
    `get_connection` was not enough on its own -- a plain Python `list[float]`
    parameter still round-trips through psycopg as a `double precision[]`
    array literal, and `<=>` has no operator overload for
    `vector <=> double precision[]` (`UndefinedFunction` at query time).
    pgvector defines an explicit `double precision[] -> vector` CAST, so
    casting the parameter (`%s::vector`) resolves it; relying on adapter
    registration alone did not.

    `masked` (EC-IN-04, TSD-edge-cases.md D-4.1): `None` (the default)
    preserves the EXACT pre-EC-IN-04 query byte-for-byte -- no `masked`
    column reference at all -- so every caller that doesn't pass this
    parameter (every call site before this task, and every call site when
    `Settings.dual_mode_threshold_enabled` is `False`) is a zero-regression,
    identical query. `True`/`False` add an `AND masked = %s` filter, used by
    `ai_inference.pipeline.recognize`'s masked-probe decision path to search
    ONLY `face_embeddings.masked=true` templates (synthetic_masked/backfill)
    first, falling back to `masked=False` (or unfiltered) per OQ-3 when that
    filtered search finds nothing. See the migration that adds a partial
    HNSW index on `masked=true`
    (`ix_face_embeddings_vector_hnsw_cosine_masked`) for why this filter
    stays within the <2ms overhead budget: the filtered query lands on its
    OWN small, dedicated ANN index (a fraction of the full gallery's size,
    since masked templates are 2-3/user vs ~13/user total) rather than a
    full-index scan + post-filter.
    """
    if masked is None:
        cursor.execute(
            "SELECT user_id, 1 - (vector <=> %s::vector) AS similarity FROM face_embeddings "
            "WHERE model_version = %s ORDER BY vector <=> %s::vector ASC LIMIT %s",
            (embedding, model_version, embedding, k),
        )
    else:
        cursor.execute(
            "SELECT user_id, 1 - (vector <=> %s::vector) AS similarity FROM face_embeddings "
            "WHERE model_version = %s AND masked = %s "
            "ORDER BY vector <=> %s::vector ASC LIMIT %s",
            (embedding, model_version, masked, embedding, k),
        )
    rows = cursor.fetchall()
    return [(str(user_id), float(similarity)) for user_id, similarity in rows]


def get_device_class(cursor: Cursor, device_id: str) -> str | None:
    """`devices.device_class` for `device_id`, or `None` if the device row
    doesn't exist or its `device_class` is NULL (pre-D-5 legacy row).

    Used by `ai_inference.pipeline.recognize`'s EC-IN-04 threshold
    resolution to build the `DEVICE_CLASS` scope candidate for
    `get_recognition_config_override` below -- `ai_inference_ro` already has
    SELECT on `devices` (migration `d4e8a2f6c1b9`, granted for IN-02 device
    auth), so no new grant is needed for this read.
    """
    cursor.execute("SELECT device_class FROM devices WHERE id = %s", (device_id,))
    row = cursor.fetchone()
    if row is None or row[0] is None:
        return None
    return str(row[0])


def get_recognition_config_override(
    cursor: Cursor,
    *,
    mode: str,
    device_class: str | None,
) -> dict[str, float | int | None] | None:
    """The single most-specific `recognition_configs` override row for
    `mode`, checked in `DEVICE_CLASS > GLOBAL` priority (EC-BE-04,
    TSD-edge-cases.md D-4.2/OQ-6) -- mirrors
    `backend/app/services/recognition_config_service.py::
    resolve_recognition_config`'s `_SCOPE_PRIORITY` ordering, minus the
    `USER` scope.

    **`USER` scope is intentionally NOT queried here** (a deliberate,
    documented gap, not an oversight): the per-request similarity_threshold/
    margin/min_frames resolved by this function are needed BEFORE a
    candidate `user_id` is even known (that's the whole point of a
    threshold -- deciding whether a computed similarity is high enough to
    NAME a user), so a `(USER, user_id)` scope candidate cannot be built at
    this call site. `USER`-scoped overrides (D-4.4's high-similarity-pair
    `threshold_override`) remain a later consumer's concern (the
    adaptive-template/high-similarity job, D-4.4/D-6, applied AFTER a match
    is tentatively made) -- not resolved by `/recognize`'s pre-match
    threshold lookup.

    Returns a plain dict (not `ResolvedRecognitionConfig` -- that dataclass
    lives in `backend/`, a separate deployable ai-inference does not import,
    same "no cross-service import" convention as `ai_inference.device_auth`
    re-implementing backend's device-auth logic) with keys
    `similarity_threshold`/`margin`/`liveness_threshold`/`min_frames`, or
    `None` if no DEVICE_CLASS or GLOBAL row exists for `mode` at all.
    Fields present but `NULL` on the matched row are returned as `None` in
    the dict (means "not overridden here" -- same OQ-6 contract as backend's
    version), NOT backfilled from the other scope.
    """
    if device_class is not None:
        cursor.execute(
            "SELECT similarity_threshold, margin, liveness_threshold, min_frames "
            "FROM recognition_configs WHERE mode = %s AND scope = 'device_class' "
            "AND scope_ref = %s",
            (mode, device_class),
        )
        row = cursor.fetchone()
        if row is not None:
            return _override_row_to_dict(row)

    cursor.execute(
        "SELECT similarity_threshold, margin, liveness_threshold, min_frames "
        "FROM recognition_configs WHERE mode = %s AND scope = 'global' "
        "AND scope_ref IS NULL",
        (mode,),
    )
    row = cursor.fetchone()
    if row is not None:
        return _override_row_to_dict(row)
    return None


def _override_row_to_dict(row: tuple[Any, ...]) -> dict[str, float | int | None]:
    similarity_threshold, margin, liveness_threshold, min_frames = row
    return {
        "similarity_threshold": (
            float(similarity_threshold) if similarity_threshold is not None else None
        ),
        "margin": float(margin) if margin is not None else None,
        "liveness_threshold": (
            float(liveness_threshold) if liveness_threshold is not None else None
        ),
        "min_frames": int(min_frames) if min_frames is not None else None,
    }
