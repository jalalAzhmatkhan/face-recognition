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


def test_applies_the_pose_tolerance_override() -> None:
    """The server-side half of the head-pose gate. Exposed in the same admin
    parameter as the frontend's sensitivity so an operator who loosens the
    browser side can loosen the QC side to match, instead of trading a
    "position never lights up" complaint for a "REJECTED_QUALITY:
    pose_out_of_range" one."""
    settings = QCSettings(pose_tolerance_deg=15.0)
    cursor = _cursor_returning({"pose_tolerance_deg": 22.0})
    assert resolve_qc_settings(cursor, settings).pose_tolerance_deg == 22.0


def test_ignores_the_frontend_only_pose_gains() -> None:
    """`yaw_gain`/`pitch_gain`/`min_pose_radius` correct the FRONTEND's
    landmark-ratio estimator, which under-reports pitch. This side uses
    solvePnP, which reports true degrees -- applying the gains here would
    double-count the correction and start passing genuinely wrong poses."""
    settings = QCSettings(yaw_range_deg=35.0, pitch_range_deg=25.0, pose_tolerance_deg=15.0)
    cursor = _cursor_returning(
        {"yaw_gain": 2.5, "pitch_gain": 3.5, "min_pose_radius": 0.55}
    )

    resolved = resolve_qc_settings(cursor, settings)

    assert resolved.yaw_range_deg == 35.0
    assert resolved.pitch_range_deg == 25.0
    assert resolved.pose_tolerance_deg == 15.0
    assert resolved == settings
