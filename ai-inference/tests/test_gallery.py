"""Unit tests for `ai_inference.gallery` against a fake DB-API cursor
(mirrors the FakeCursor idiom in `ai-training/tests/test_gallery_reembed.py`)
-- no real Postgres/psycopg/pgvector needed. Must pass on base CI (no `ml`
extra): this module must NOT import psycopg/pgvector at module level."""

from ai_inference import gallery


class FakeCursor:
    """Dispatches on query prefix."""

    def __init__(
        self,
        *,
        production_version: str | None = None,
        rows: list[tuple[str, float]] | None = None,
        device_class: str | None = None,
        config_override_rows: dict[str, tuple] | None = None,
    ) -> None:
        self.production_version = production_version
        self.rows = rows or []
        # EC-IN-04 test fixtures: device_class keyed by device_id is not
        # needed (single-device tests only need one fixed answer), and
        # config_override_rows keys on "device_class:<mode>" /
        # "global:<mode>" so a single FakeCursor can serve both queries
        # `get_recognition_config_override` issues.
        self.device_class = device_class
        self.config_override_rows = config_override_rows or {}
        self.executed: list[tuple[str, tuple]] = []
        self._fetch_one: tuple | None = None
        self._fetch_all: list[tuple] = []

    def execute(self, query: str, params: tuple = ()) -> None:
        self.executed.append((query, params))
        if query.startswith("SELECT version FROM models"):
            self._fetch_one = (self.production_version,) if self.production_version else None
        elif query.startswith("SELECT user_id, 1 - (vector <=> %s::vector)"):
            self._fetch_all = list(self.rows)
        elif query.startswith("SELECT device_class FROM devices"):
            self._fetch_one = (self.device_class,) if self.device_class is not None else None
        elif query.startswith(
            "SELECT similarity_threshold, margin, liveness_threshold, min_frames"
        ):
            if "scope = 'device_class'" in query:
                mode = params[0]
                key = f"device_class:{mode}"
            else:
                mode = params[0]
                key = f"global:{mode}"
            self._fetch_one = self.config_override_rows.get(key)
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


def test_get_current_production_model_version_filters_to_embedder_kind() -> None:
    """EC-BE-06 regression: a liveness model can ALSO be PRODUCTION at the
    same time as an embedder now -- this query must never return a
    liveness model's version as if it were the embedder's."""
    cursor = FakeCursor(production_version="v1", rows=[])
    gallery.get_current_production_model_version(cursor)
    query, _params = cursor.executed[0]
    assert "model_kind = 'embedder'" in query


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


# --- EC-IN-04: masked filter on search_top_k ---------------------------


def test_search_top_k_masked_none_is_byte_identical_to_pre_ec_in_04_query() -> None:
    """Regression: the default (`masked=None`) call must issue the EXACT
    same SQL/params as before this task -- no `masked` column reference at
    all, not even a no-op `AND masked = %s` clause -- since this is the
    only call shape every existing/flag-off caller uses."""
    cursor = FakeCursor(rows=[])
    embedding = [0.5] * 512
    gallery.search_top_k(cursor, embedding=embedding, model_version="adaface-v3", k=25)
    query, params = cursor.executed[0]
    assert "masked" not in query
    assert query == (
        "SELECT user_id, 1 - (vector <=> %s::vector) AS similarity FROM face_embeddings "
        "WHERE model_version = %s ORDER BY vector <=> %s::vector ASC LIMIT %s"
    )
    assert params == (embedding, "adaface-v3", embedding, 25)


def test_search_top_k_masked_true_adds_filter() -> None:
    cursor = FakeCursor(rows=[("user-a", 0.9)])
    embedding = [0.1] * 512
    result = gallery.search_top_k(
        cursor, embedding=embedding, model_version="v1", k=10, masked=True
    )
    query, params = cursor.executed[0]
    assert "AND masked = %s" in query
    assert params == (embedding, "v1", True, embedding, 10)
    assert result == [("user-a", 0.9)]


def test_search_top_k_masked_false_adds_filter() -> None:
    cursor = FakeCursor(rows=[])
    embedding = [0.1] * 512
    gallery.search_top_k(cursor, embedding=embedding, model_version="v1", k=10, masked=False)
    query, params = cursor.executed[0]
    assert "AND masked = %s" in query
    assert params == (embedding, "v1", False, embedding, 10)


# --- EC-IN-04: get_device_class -----------------------------------------


def test_get_device_class_found() -> None:
    cursor = FakeCursor(device_class="door_entry")
    assert gallery.get_device_class(cursor, "device-1") == "door_entry"


def test_get_device_class_none_when_device_missing() -> None:
    cursor = FakeCursor(device_class=None)
    assert gallery.get_device_class(cursor, "unknown-device") is None


def test_get_device_class_query_shape() -> None:
    cursor = FakeCursor(device_class="attendance")
    gallery.get_device_class(cursor, "device-1")
    query, params = cursor.executed[0]
    assert query == "SELECT device_class FROM devices WHERE id = %s"
    assert params == ("device-1",)


# --- EC-IN-04: get_recognition_config_override --------------------------


def test_get_recognition_config_override_none_when_no_rows_at_all() -> None:
    cursor = FakeCursor()
    result = gallery.get_recognition_config_override(
        cursor, mode="masked", device_class="door_entry"
    )
    assert result is None
    # Both DEVICE_CLASS and GLOBAL queries were attempted.
    assert len(cursor.executed) == 2


def test_get_recognition_config_override_device_class_wins_over_global() -> None:
    cursor = FakeCursor(
        config_override_rows={
            "device_class:masked": (0.28, None, None, None),
            "global:masked": (0.31, 0.02, 0.6, 3),
        }
    )
    result = gallery.get_recognition_config_override(
        cursor, mode="masked", device_class="door_entry"
    )
    assert result == {
        "similarity_threshold": 0.28,
        "margin": None,
        "liveness_threshold": None,
        "min_frames": None,
    }
    # DEVICE_CLASS matched -- GLOBAL query never even issued.
    assert len(cursor.executed) == 1


def test_get_recognition_config_override_falls_back_to_global_when_no_device_class_row() -> None:
    cursor = FakeCursor(
        config_override_rows={"global:normal": (0.4, 0.05, None, 2)}
    )
    result = gallery.get_recognition_config_override(
        cursor, mode="normal", device_class="attendance"
    )
    assert result == {
        "similarity_threshold": 0.4,
        "margin": 0.05,
        "liveness_threshold": None,
        "min_frames": 2,
    }
    assert len(cursor.executed) == 2  # DEVICE_CLASS miss, then GLOBAL hit


def test_get_recognition_config_override_skips_device_class_query_when_none() -> None:
    cursor = FakeCursor(config_override_rows={"global:masked": (0.3, None, None, None)})
    result = gallery.get_recognition_config_override(cursor, mode="masked", device_class=None)
    assert result is not None
    assert len(cursor.executed) == 1  # only the GLOBAL query, no DEVICE_CLASS one
