"""TR-04 dataset-snapshot build/load against a mocked DB cursor + mocked S3
client (no real Postgres/S3 - per task instructions)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

import ai_training.data.snapshots as snapshots_module
from ai_training.config import Settings
from ai_training.data.snapshots import DatasetSnapshot, MediaEntry, build_snapshot, load_snapshot


class _FakeCursor:
    """Minimal cursor-shaped fake supporting the `with conn.cursor() as
    cursor:` context-manager usage in `build_snapshot`, backed by a plain
    row list so `find_enrolled_media`'s real SQL-building logic is
    exercised end-to-end alongside `build_snapshot`."""

    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows
        self.executed: list[tuple] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def execute(self, query: str, params: tuple = ()) -> None:
        self.executed.append((query, params))

    def fetchall(self) -> list[tuple]:
        return self._rows


class _FakeConnection:
    def __init__(self, rows: list[tuple]) -> None:
        self._cursor = _FakeCursor(rows)
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return self._cursor

    def close(self) -> None:
        self.closed = True


def _settings() -> Settings:
    return Settings(_env_file=None)


_ROWS = [
    ("user-1", "session-1", "video", "frac-media", "enrollment/user-1/session-1/rotation.webm"),
    ("user-1", "session-1", "photo", "frac-media", "enrollment/user-1/session-1/photo_1.jpg"),
    ("user-2", "session-2", "video", "frac-media", "enrollment/user-2/session-2/rotation.webm"),
]


def test_build_snapshot_builds_manifest_from_db_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_conn = _FakeConnection(_ROWS)
    monkeypatch.setattr(snapshots_module, "get_connection", lambda dsn: fake_conn)
    s3 = MagicMock()

    snapshot = build_snapshot(_settings(), {"external_ref": "EMP001"}, s3_client=s3)

    assert snapshot.total_media_count == 3
    assert snapshot.user_ids == ["user-1", "user-2"]
    assert snapshot.session_ids == ["session-1", "session-2"]
    assert snapshot.media_keys == [
        "enrollment/user-1/session-1/rotation.webm",
        "enrollment/user-1/session-1/photo_1.jpg",
        "enrollment/user-2/session-2/rotation.webm",
    ]
    assert snapshot.media_bucket == "frac-media"
    assert snapshot.filters == {"external_ref": "EMP001"}
    # snapshot_id is a real uuid4, not derived from the filters/time.
    import uuid

    assert uuid.UUID(snapshot.snapshot_id).version == 4
    # Connection is always closed, even though nothing raised here.
    assert fake_conn.closed is True


def test_build_snapshot_closes_connection_even_when_query_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_conn = _FakeConnection([])
    monkeypatch.setattr(snapshots_module, "get_connection", lambda dsn: fake_conn)

    with pytest.raises(ValueError):
        build_snapshot(_settings(), {"bogus": "x"}, s3_client=MagicMock())

    assert fake_conn.closed is True


def test_build_snapshot_uploads_manifest_to_expected_s3_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_conn = _FakeConnection(_ROWS)
    monkeypatch.setattr(snapshots_module, "get_connection", lambda dsn: fake_conn)
    s3 = MagicMock()
    settings = _settings()

    snapshot = build_snapshot(settings, s3_client=s3)

    s3.put_object.assert_called_once()
    _args, kwargs = s3.put_object.call_args
    assert kwargs["Bucket"] == settings.s3.bucket
    assert kwargs["Key"] == f"datasets/{snapshot.snapshot_id}/manifest.json"
    body = json.loads(kwargs["Body"])
    assert body["snapshot_id"] == snapshot.snapshot_id
    assert body["total_media_count"] == 3


def test_build_snapshot_two_runs_with_identical_filters_get_different_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`snapshot_id` must not collide even for byte-identical filters/data -
    see `build_snapshot`'s docstring on why it's a fresh uuid4 each call."""
    monkeypatch.setattr(
        snapshots_module, "get_connection", lambda dsn: _FakeConnection(_ROWS)
    )
    first = build_snapshot(_settings(), {"external_ref": "EMP001"}, s3_client=MagicMock())
    second = build_snapshot(_settings(), {"external_ref": "EMP001"}, s3_client=MagicMock())
    assert first.snapshot_id != second.snapshot_id


def test_load_snapshot_round_trips_manifest_written_by_build_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The concrete "reproducible by id" guarantee: whatever `build_snapshot`
    uploaded is exactly what `load_snapshot` returns."""
    fake_conn = _FakeConnection(_ROWS)
    monkeypatch.setattr(snapshots_module, "get_connection", lambda dsn: fake_conn)

    uploaded: dict[str, bytes] = {}

    def _fake_put_object(*, Bucket: str, Key: str, Body: bytes, ContentType: str) -> None:
        uploaded[Key] = Body

    s3_write = MagicMock()
    s3_write.put_object.side_effect = lambda **kwargs: _fake_put_object(**kwargs)

    built = build_snapshot(_settings(), {"external_ref": "EMP001"}, s3_client=s3_write)

    key = f"datasets/{built.snapshot_id}/manifest.json"
    s3_read = MagicMock()
    s3_read.get_object.return_value = {"Body": _BytesReader(uploaded[key])}

    loaded = load_snapshot(_settings(), built.snapshot_id, s3_client=s3_read)

    assert loaded == built
    s3_read.get_object.assert_called_once_with(
        Bucket=_settings().s3.bucket, Key=key
    )


class _BytesReader:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


def test_build_snapshot_propagates_event_frame_source_and_none_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EC-TR-05: an event-frame row with no matched identity keeps
    `user_id`/`session_id` as `None` (never coerced to a placeholder
    string), and `source` survives into the manifest's `MediaEntry`."""
    rows = [(None, None, "event_frame", "frac-media", "frame1.jpg")]
    fake_conn = _FakeConnection(rows)
    monkeypatch.setattr(snapshots_module, "get_connection", lambda dsn: fake_conn)

    snapshot = build_snapshot(_settings(), {"source": "event_frame"}, s3_client=MagicMock())

    assert snapshot.user_ids == []
    assert snapshot.session_ids == []
    assert snapshot.media[0].source == "event_frame"
    assert snapshot.media[0].user_id is None
    assert snapshot.media[0].session_id is None


def test_load_snapshot_parses_media_entries() -> None:
    manifest = DatasetSnapshot(
        snapshot_id="snap-abc",
        filters={"external_ref": "EMP001"},
        media_keys=["k1"],
        media=[MediaEntry(s3_key="k1", kind="video", user_id="u1", session_id="s1")],
        media_bucket="frac-media",
        user_ids=["u1"],
        session_ids=["s1"],
        total_media_count=1,
    )
    s3 = MagicMock()
    s3.get_object.return_value = {
        "Body": _BytesReader(manifest.model_dump_json().encode("utf-8"))
    }

    loaded = load_snapshot(_settings(), "snap-abc", s3_client=s3)

    assert loaded == manifest
    assert loaded.media[0].kind == "video"
