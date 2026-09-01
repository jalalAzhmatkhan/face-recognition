"""Raw-SQL read of backend-owned `system_parameters` against a mocked
DB-API cursor (no real Postgres, per project convention)."""

from unittest.mock import MagicMock

from ai_training.db.system_parameters_repo import get_enrollment_quality_override


def test_returns_none_when_no_row_saved_yet() -> None:
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    assert get_enrollment_quality_override(cursor) is None
    args, _kwargs = cursor.execute.call_args
    query, params = args
    assert "system_parameters" in query
    assert params == ("enrollment_capture_quality",)


def test_returns_dict_when_driver_decodes_jsonb_natively() -> None:
    cursor = MagicMock()
    cursor.fetchone.return_value = ({"min_blur_variance": 25.0},)
    assert get_enrollment_quality_override(cursor) == {"min_blur_variance": 25.0}


def test_parses_json_text_when_driver_returns_raw_string() -> None:
    cursor = MagicMock()
    cursor.fetchone.return_value = ('{"min_blur_variance": 25.0}',)
    assert get_enrollment_quality_override(cursor) == {"min_blur_variance": 25.0}
