"""Lazy `psycopg` connection helper (TR-02/TR-03)."""

from __future__ import annotations

from typing import Any


def get_connection(dsn: str) -> Any:
    """Open a `psycopg` (v3) connection and register the `pgvector` adapter
    so Python `list[float]` <-> the `vector` column type round-trips
    correctly for `face_embeddings.vector` inserts.
    """
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - psycopg is a base dependency
        raise RuntimeError("DB access requires 'psycopg[binary]' (see pyproject.toml).") from exc

    conn = psycopg.connect(dsn)
    try:
        from pgvector.psycopg import register_vector

        register_vector(conn)
    except ImportError:  # pragma: no cover - pgvector is a base dependency
        # Don't hard-fail connection setup for callers that only need
        # non-vector tables (e.g. reading enrollment_sessions.state).
        pass
    return conn
