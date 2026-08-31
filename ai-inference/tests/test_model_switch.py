"""Unit tests for `ai_inference.model_switch` (IN-07): pure Python +
`time.monotonic` -- no DB/torch, must pass on base CI (no `ml` extra)."""

from ai_inference.model_switch import ProductionVersionCache, embedder_matches_production


class _FakeCursor:
    """Returns a configurable sequence of `models.version` values, one per
    real (non-cached) call -- mirrors `ai_inference.gallery`'s query shape
    closely enough for `ProductionVersionCache` (it only ever calls
    `gallery.get_current_production_model_version(cursor)`, which this
    fakes out at the module level below)."""

    def __init__(self, versions: list[str | None]) -> None:
        self._versions = list(versions)
        self.call_count = 0

    def execute(self, query, params=()):
        self.call_count += 1

    def fetchone(self):
        version = self._versions[min(self.call_count - 1, len(self._versions) - 1)]
        return (version,) if version is not None else None


def test_cache_returns_fresh_value_on_first_call() -> None:
    cache = ProductionVersionCache(ttl_seconds=60.0)
    cursor = _FakeCursor(["v1"])
    assert cache.get(cursor) == "v1"
    assert cursor.call_count == 1


def test_cache_reuses_value_within_ttl(monkeypatch) -> None:
    fake_time = [1000.0]
    monkeypatch.setattr("time.monotonic", lambda: fake_time[0])

    cache = ProductionVersionCache(ttl_seconds=60.0)
    cursor = _FakeCursor(["v1", "v2"])
    assert cache.get(cursor) == "v1"

    fake_time[0] += 10.0  # well within the 60s TTL
    assert cache.get(cursor) == "v1"
    assert cursor.call_count == 1  # second call served from cache, no re-query


def test_cache_re_queries_after_ttl_expires(monkeypatch) -> None:
    fake_time = [1000.0]
    monkeypatch.setattr("time.monotonic", lambda: fake_time[0])

    cache = ProductionVersionCache(ttl_seconds=5.0)
    cursor = _FakeCursor(["v1", "v2"])
    assert cache.get(cursor) == "v1"

    fake_time[0] += 10.0  # past the 5s TTL
    assert cache.get(cursor) == "v2"
    assert cursor.call_count == 2


def test_cache_invalidate_forces_re_query() -> None:
    cache = ProductionVersionCache(ttl_seconds=60.0)
    cursor = _FakeCursor(["v1", "v2"])
    assert cache.get(cursor) == "v1"
    cache.invalidate()
    assert cache.get(cursor) == "v2"
    assert cursor.call_count == 2


def test_cache_none_production_version_is_cached_too() -> None:
    """No PRODUCTION model is a valid, cacheable state -- callers must
    still get `None` (fail-secure), not a re-query storm."""
    cache = ProductionVersionCache(ttl_seconds=60.0)
    cursor = _FakeCursor([None])
    assert cache.get(cursor) is None
    assert cache.get(cursor) is None
    assert cursor.call_count == 1


def test_embedder_matches_production_true_when_equal() -> None:
    assert embedder_matches_production("adaface-ir101-webface12m", "adaface-ir101-webface12m")


def test_embedder_matches_production_false_when_different() -> None:
    assert not embedder_matches_production("adaface-ir101-webface12m", "adaface-ir50-webface12m")
