"""Unit tests for `ai_inference.gallery` against a fake DB-API cursor
(mirrors the FakeCursor idiom in `ai-training/tests/test_gallery_reembed.py`)
-- no real Postgres/psycopg/pgvector needed. Must pass on base CI (no `ml`
extra): this module must NOT import psycopg/pgvector at module level."""

from ai_inference import gallery


class FakeCursor:
    """Dispatches on query prefix."""

    def __init__(self, *, production_version: str | None, rows: list[tuple[str, float]]) -> None:
        self.production_version = production_version
        self.rows = rows
        self.executed: list[tuple[str, tuple]] = []
        self._fetch_one: tuple | None = None
        self._fetch_all: list[tuple] = []

    def execute(self, query: str, params: tuple = ()) -> None:
        self.executed.append((query, params))
        if query.startswith("SELECT version FROM models"):
            self._fetch_one = (self.production_version,) if self.production_version else None
        elif query.startswith("SELECT user_id, 1 - (vector <=> %s::vector)"):
            self._fetch_all = list(self.rows)
        else:  # pragma: no cover - not exercised by these tests
            self._fetch_one = None
            self._fetch_all = []

    def fetchone(self):
        return self._fetch_one

    def fetchall(self):
        return self._fetch_all


def test_get_current_production_model_version_found() -> None:
    cursor = FakeCursor(production_version="adaface-ir101-webface12m-v2", rows=[])
    assert gallery.get_current_production_model_version(cursor) == "adaface-ir101-webface12m-v2"


def test_get_current_production_model_version_none() -> None:
    """Fail-secure contract: no PRODUCTION row -> None, not an exception."""
    cursor = FakeCursor(production_version=None, rows=[])
    assert gallery.get_current_production_model_version(cursor) is None


def test_get_current_production_model_version_query_has_no_other_table() -> None:
    cursor = FakeCursor(production_version="v1", rows=[])
    gallery.get_current_production_model_version(cursor)
    query, _params = cursor.executed[0]
    assert "FROM models" in query
    assert "stage = 'PRODUCTION'" in query
    assert "face_embeddings" not in query


def test_search_top_k_returns_rows_in_query_order() -> None:
    cursor = FakeCursor(
        production_version=None,
        rows=[("user-a", 0.91), ("user-b", 0.80), ("user-a", 0.70)],
    )
    result = gallery.search_top_k(
        cursor, embedding=[0.1, 0.2, 0.3], model_version="adaface-v2", k=50
    )
    assert result == [("user-a", 0.91), ("user-b", 0.80), ("user-a", 0.70)]


def test_search_top_k_query_scoped_to_model_version_and_limit() -> None:
    cursor = FakeCursor(production_version=None, rows=[])
    embedding = [0.5] * 512
    gallery.search_top_k(cursor, embedding=embedding, model_version="adaface-v3", k=25)
    query, params = cursor.executed[0]
    assert "FROM face_embeddings" in query
    assert "WHERE model_version = %s" in query
    assert "ORDER BY vector <=> %s::vector ASC" in query
    assert "LIMIT %s" in query
    assert params == (embedding, "adaface-v3", embedding, 25)


def test_search_top_k_empty_gallery_returns_empty_list() -> None:
    cursor = FakeCursor(production_version=None, rows=[])
    result = gallery.search_top_k(cursor, embedding=[0.0], model_version="v1", k=50)
    assert result == []


def test_get_connection_raises_actionable_error_without_ml_extra(monkeypatch) -> None:
    """Without the `ml` extra, `psycopg` isn't installed -- get_connection
    must raise a clear RuntimeError, not a bare ImportError/ModuleNotFoundError.
    This test only makes a real assertion in a base (no `ml` extra) env; if
    psycopg IS installed (e.g. this test happens to run inside the `ml`
    extra's venv), it's skipped instead of asserting the wrong thing."""
    import importlib

    try:
        importlib.import_module("psycopg")
    except ImportError:
        pass
    else:
        return  # psycopg is installed in this environment -- nothing to assert here.

    import pytest

    with pytest.raises(RuntimeError, match="ml' extra"):
        gallery.get_connection("postgresql://example/db")
