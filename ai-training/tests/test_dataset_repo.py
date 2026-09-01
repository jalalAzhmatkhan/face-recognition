"""TR-04 dataset-candidate query against a mocked DB-API cursor (no real
Postgres - per task instructions, automated tests never touch it)."""

from unittest.mock import MagicMock

import pytest

from ai_training.db.dataset_repo import MediaRecord, find_enrolled_media


def test_find_enrolled_media_maps_rows_to_media_records() -> None:
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        ("user-1", "session-1", "video", "frac-media", "enrollment/u1/s1/rotation.webm"),
        ("user-1", "session-1", "photo", "frac-media", "enrollment/u1/s1/photo_1.jpg"),
    ]
    records = find_enrolled_media(cursor)
    assert records == [
        MediaRecord(
            user_id="user-1",
            session_id="session-1",
            kind="video",
            s3_bucket="frac-media",
            s3_key="enrollment/u1/s1/rotation.webm",
        ),
        MediaRecord(
            user_id="user-1",
            session_id="session-1",
            kind="photo",
            s3_bucket="frac-media",
            s3_key="enrollment/u1/s1/photo_1.jpg",
        ),
    ]


def test_find_enrolled_media_base_query_filters_finalized_and_enrolled() -> None:
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    find_enrolled_media(cursor)
    args, _kwargs = cursor.execute.call_args
    query, params = args
    assert "mo.status = 'FINALIZED'" in query
    assert "es.state = 'ENROLLED'" in query
    assert params == ()


def test_find_enrolled_media_applies_external_ref_filter() -> None:
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    find_enrolled_media(cursor, {"external_ref": "EMP001"})
    args, _kwargs = cursor.execute.call_args
    query, params = args
    assert "u.external_ref = %s" in query
    assert params == ("EMP001",)


def test_find_enrolled_media_applies_created_after_and_before_filters() -> None:
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    find_enrolled_media(
        cursor, {"created_after": "2026-01-01", "created_before": "2026-06-01"}
    )
    args, _kwargs = cursor.execute.call_args
    query, params = args
    assert "mo.created_at >= %s" in query
    assert "mo.created_at < %s" in query
    assert params == ("2026-01-01", "2026-06-01")


def test_find_enrolled_media_applies_kind_filter() -> None:
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    find_enrolled_media(cursor, {"kind": "video"})
    args, _kwargs = cursor.execute.call_args
    query, params = args
    assert "mo.kind = %s" in query
    assert params == ("video",)


def test_find_enrolled_media_combines_multiple_filters_in_declared_order() -> None:
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    find_enrolled_media(
        cursor,
        {"external_ref": "EMP001", "kind": "video", "created_after": "2026-01-01"},
    )
    args, _kwargs = cursor.execute.call_args
    _query, params = args
    assert params == ("EMP001", "video", "2026-01-01")


def test_find_enrolled_media_rejects_unknown_filter_key() -> None:
    cursor = MagicMock()
    with pytest.raises(ValueError, match="unsupported filter"):
        find_enrolled_media(cursor, {"bogus": "x"})
    cursor.execute.assert_not_called()


def test_find_enrolled_media_orders_by_created_at_ascending() -> None:
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    find_enrolled_media(cursor)
    args, _kwargs = cursor.execute.call_args
    query, _params = args
    assert query.strip().endswith("ORDER BY mo.created_at ASC")


def test_find_enrolled_media_defaults_source_to_enrollment() -> None:
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        ("user-1", "session-1", "video", "frac-media", "enrollment/u1/s1/rotation.webm"),
    ]
    records = find_enrolled_media(cursor)
    assert records[0].source == "enrollment"


def test_find_enrolled_media_applies_variant_filter_on_enrollment_source() -> None:
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    find_enrolled_media(cursor, {"variant": "glasses"})
    args, _kwargs = cursor.execute.call_args
    query, params = args
    assert "mo.variant = %s" in query
    assert "JOIN enrollment_sessions" in query
    assert params == ("glasses",)


def test_find_enrolled_media_rejects_unsupported_source() -> None:
    cursor = MagicMock()
    with pytest.raises(ValueError, match="unsupported source"):
        find_enrolled_media(cursor, {"source": "bogus"})
    cursor.execute.assert_not_called()


class TestEventFrameSource:
    """EC-TR-05 (TSD-EC B-4): `source=event_frame` selects door-camera
    frames (no enrollment session) joined to `access_events` for
    `condition_flags` filtering."""

    def test_queries_media_objects_with_null_session_id_and_event_frame_kind(self) -> None:
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        find_enrolled_media(cursor, {"source": "event_frame"})
        args, _kwargs = cursor.execute.call_args
        query, params = args
        assert "mo.session_id IS NULL" in query
        assert "mo.kind = 'event_frame'" in query
        assert "LEFT JOIN access_events" in query
        assert params == ()

    def test_maps_matched_user_id_to_media_record_user_id(self) -> None:
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            ("user-9", None, "event_frame", "frac-media", "pad-unrelated/frame1.jpg"),
        ]
        records = find_enrolled_media(cursor, {"source": "event_frame"})
        assert records == [
            MediaRecord(
                user_id="user-9",
                session_id=None,
                kind="event_frame",
                s3_bucket="frac-media",
                s3_key="pad-unrelated/frame1.jpg",
                source="event_frame",
            )
        ]

    def test_unmatched_frame_has_none_user_id_not_a_crash_or_placeholder_string(self) -> None:
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            (None, None, "event_frame", "frac-media", "frame2.jpg"),
        ]
        records = find_enrolled_media(cursor, {"source": "event_frame"})
        assert records[0].user_id is None
        assert records[0].session_id is None

    def test_applies_condition_flag_filter(self) -> None:
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        find_enrolled_media(cursor, {"source": "event_frame", "condition": "dark"})
        args, _kwargs = cursor.execute.call_args
        query, params = args
        assert "condition_flags ->> %s" in query
        assert params == ("dark",)

    def test_rejects_condition_without_event_frame_source(self) -> None:
        cursor = MagicMock()
        with pytest.raises(ValueError, match="requires source=event_frame"):
            find_enrolled_media(cursor, {"condition": "dark"})
        cursor.execute.assert_not_called()

    def test_rejects_unsupported_condition_flag(self) -> None:
        cursor = MagicMock()
        with pytest.raises(ValueError, match="unsupported condition"):
            find_enrolled_media(cursor, {"source": "event_frame", "condition": "drak"})
        cursor.execute.assert_not_called()

    def test_rejects_kind_filter_with_event_frame_source(self) -> None:
        cursor = MagicMock()
        with pytest.raises(ValueError, match="not valid with source=event_frame"):
            find_enrolled_media(cursor, {"source": "event_frame", "kind": "photo"})
        cursor.execute.assert_not_called()

    def test_rejects_external_ref_filter_with_event_frame_source(self) -> None:
        cursor = MagicMock()
        with pytest.raises(ValueError, match="not valid with source=event_frame"):
            find_enrolled_media(cursor, {"source": "event_frame", "external_ref": "EMP001"})
        cursor.execute.assert_not_called()

    def test_applies_variant_filter_on_event_frame_source(self) -> None:
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        find_enrolled_media(cursor, {"source": "event_frame", "variant": "default"})
        args, _kwargs = cursor.execute.call_args
        _query, params = args
        assert params == ("default",)
