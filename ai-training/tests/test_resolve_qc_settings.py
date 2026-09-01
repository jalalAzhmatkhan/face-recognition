"""`resolve_qc_settings` (System Parameter admin-menu override on top of
`QCSettings`) against a mocked DB-API cursor -- no real Postgres, no cv2/
mediapipe (this function never touches either)."""

from unittest.mock import MagicMock

from ai_training.config import QCSettings
from ai_training.quality.pipeline import resolve_qc_settings


def _cursor_returning(value: dict | None) -> MagicMock:
    cursor = MagicMock()
    cursor.fetchone.return_value = (value,) if value is not None else None
    return cursor


def test_returns_settings_unchanged_when_no_override_saved() -> None:
    settings = QCSettings()
    cursor = _cursor_returning(None)
    resolved = resolve_qc_settings(cursor, settings)
    assert resolved == settings
    assert resolved.blur_variance_min == settings.blur_variance_min


def test_applies_all_three_overridden_fields() -> None:
    settings = QCSettings(blur_variance_min=80.0, brightness_min=40.0, brightness_max=215.0)
    cursor = _cursor_returning(
        {"min_blur_variance": 30.0, "min_brightness": 35.0, "max_brightness": 225.0}
    )
    resolved = resolve_qc_settings(cursor, settings)
    assert resolved.blur_variance_min == 30.0
    assert resolved.brightness_min == 35.0
    assert resolved.brightness_max == 225.0


def test_applies_partial_override_leaving_other_fields_at_settings_default() -> None:
    settings = QCSettings(blur_variance_min=80.0, brightness_min=40.0, brightness_max=215.0)
    cursor = _cursor_returning({"min_blur_variance": 30.0})
    resolved = resolve_qc_settings(cursor, settings)
    assert resolved.blur_variance_min == 30.0
    assert resolved.brightness_min == 40.0
    assert resolved.brightness_max == 215.0


def test_never_touches_unrelated_qc_settings_fields() -> None:
    settings = QCSettings(face_ratio_min=0.12, min_pass_ratio=0.75)
    cursor = _cursor_returning({"min_blur_variance": 30.0})
    resolved = resolve_qc_settings(cursor, settings)
    assert resolved.face_ratio_min == 0.12
    assert resolved.min_pass_ratio == 0.75
