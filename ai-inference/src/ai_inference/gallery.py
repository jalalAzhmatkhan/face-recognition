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
    """The `models.version` currently `stage = 'PRODUCTION'`, or `None` if
    there isn't one.

    Fail-secure contract (IN-03 task brief): callers MUST treat `None` as
    "no gallery search is possible right now" and return `UNKNOWN` for every
    frame, never a 500 -- there being no PRODUCTION model is an expected,
    not exceptional, operational state (e.g. before the first promotion).

    If more than one row is somehow `stage = 'PRODUCTION'` (should not
    happen -- IN-07's atomic switch is meant to prevent it, but this module
    does not assume that invariant holds), the most recently promoted one
    wins (`ORDER BY promoted_at DESC NULLS LAST`), which is the least
    surprising tie-break and does not require a schema change here to
    enforce at the DB level.
    """
    cursor.execute(
        "SELECT version FROM models WHERE stage = 'PRODUCTION' "
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
    """
    cursor.execute(
        "SELECT user_id, 1 - (vector <=> %s::vector) AS similarity FROM face_embeddings "
        "WHERE model_version = %s ORDER BY vector <=> %s::vector ASC LIMIT %s",
        (embedding, model_version, embedding, k),
    )
    rows = cursor.fetchall()
    return [(str(user_id), float(similarity)) for user_id, similarity in rows]
