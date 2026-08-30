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
