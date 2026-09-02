"""Neutral-pose calibration math (`apply_neutral_offset`) -- pure numbers,
no cv2/mediapipe/Postgres.

Context: `ai_training.quality.pose.estimate_pose_from_landmarks` reports a
large POSITIVE (upward) pitch for a frontal face (a real portrait measured
+24.3 deg against a +-25 deg range, see that module's comments), which made
clock positions 4-8 unreachable in pilot capture. These tests pin the
correction that removes that bias.
"""

import math

import pytest

from ai_training.config import QCSettings
from ai_training.quality.pipeline import apply_neutral_offset
from ai_training.quality.pose import clock_position_targets, nearest_clock_position


def _settings() -> QCSettings:
    return QCSettings()


def test_no_baseline_leaves_the_pose_untouched() -> None:
    settings = _settings()
    assert apply_neutral_offset(12.0, -3.0, None, settings=settings) == (12.0, -3.0)


def test_neutral_reading_maps_to_the_origin() -> None:
    settings = _settings()
    # The whole point: a subject sitting still must land at (0, 0), not at
    # "12 o'clock", after calibration.
    assert apply_neutral_offset(1.0, 24.3, (1.0, 24.3), settings=settings) == (0.0, 0.0)


def test_offset_saturates_at_one_full_axis_range() -> None:
    settings = _settings()
    yaw, pitch = apply_neutral_offset(0.0, 0.0, (999.0, -999.0), settings=settings)
    assert yaw == pytest.approx(-settings.yaw_range_deg)
    assert pitch == pytest.approx(settings.pitch_range_deg)


def test_a_large_but_genuine_baseline_is_not_truncated() -> None:
    """The measured bias is ~97% of `pitch_range_deg`, so any cap tighter
    than one full range removes only PART of it -- which looks like a fix
    while leaving the bottom of the clock just as unreachable. Caught for
    real during implementation; pinned here."""
    settings = _settings()
    neutral = (0.0, 24.3)
    assert apply_neutral_offset(0.0, 24.3, neutral, settings=settings)[1] == pytest.approx(0.0)


def test_6_oclock_is_out_of_pose_tolerance_uncalibrated_and_within_it_after() -> None:
    """6 o'clock is the one bottom position the bias does NOT mislabel (it
    sits on the vertical axis, so the angle stays 180 deg) -- it fails the
    OTHER gate instead: `pose_error` against the target. Both mechanisms
    have to be fixed for the bottom half to work, so both are pinned."""
    settings = _settings()
    neutral_pitch = 24.3
    target = clock_position_targets(settings.yaw_range_deg, settings.pitch_range_deg)["06"]
    # Subject tilts down by a full pitch range from their own neutral.
    raw_pitch = neutral_pitch - settings.pitch_range_deg

    assert (
        nearest_clock_position(
            0.0,
            raw_pitch,
            yaw_range_deg=settings.yaw_range_deg,
            pitch_range_deg=settings.pitch_range_deg,
        )
        == "06"
    )
    uncalibrated_error = math.hypot(0.0 - target.yaw_deg, raw_pitch - target.pitch_deg)
    assert uncalibrated_error > settings.pose_tolerance_deg  # rejected: pose_out_of_range

    _yaw, pitch = apply_neutral_offset(0.0, raw_pitch, (0.0, neutral_pitch), settings=settings)
    calibrated_error = math.hypot(0.0 - target.yaw_deg, pitch - target.pitch_deg)
    assert calibrated_error <= settings.pose_tolerance_deg


def test_calibration_puts_every_clock_target_back_within_pose_tolerance() -> None:
    """A subject who hits each canonical target RELATIVE to their own
    neutral must pass the `pose_tolerance_deg` gate for that position --
    including the bottom half, which is exactly what failed before."""
    settings = _settings()
    neutral = (0.0, 24.3)
    targets = clock_position_targets(settings.yaw_range_deg, settings.pitch_range_deg)

    for position, target in targets.items():
        raw_yaw = target.yaw_deg + neutral[0]
        raw_pitch = target.pitch_deg + neutral[1]
        yaw, pitch = apply_neutral_offset(raw_yaw, raw_pitch, neutral, settings=settings)

        resolved = nearest_clock_position(
            yaw,
            pitch,
            yaw_range_deg=settings.yaw_range_deg,
            pitch_range_deg=settings.pitch_range_deg,
        )
        assert resolved == position

        pose_error = math.hypot(yaw - target.yaw_deg, pitch - target.pitch_deg)
        assert pose_error <= settings.pose_tolerance_deg


def test_without_calibration_every_bottom_position_fails_one_gate_or_the_other() -> None:
    """The negative of the test above: documents the bug being fixed, so a
    refactor that silently drops calibration fails loudly here.

    4/5/7/8 get MISLABELLED (the bias rotates the measured angle upward, so
    aiming at 5 registers as 3); 6 keeps its label but blows the pose
    tolerance. That split is exactly what made the symptom confusing in
    pilot capture -- some sectors lit up wrongly, one never lit at all.
    """
    settings = _settings()
    neutral_pitch = 24.3
    targets = clock_position_targets(settings.yaw_range_deg, settings.pitch_range_deg)

    for position in ("04", "05", "06", "07", "08"):
        target = targets[position]
        raw_yaw, raw_pitch = target.yaw_deg, target.pitch_deg + neutral_pitch
        resolved = nearest_clock_position(
            raw_yaw,
            raw_pitch,
            yaw_range_deg=settings.yaw_range_deg,
            pitch_range_deg=settings.pitch_range_deg,
        )
        pose_error = math.hypot(raw_yaw - target.yaw_deg, raw_pitch - target.pitch_deg)
        assert resolved != position or pose_error > settings.pose_tolerance_deg

    # ...while the top half sails through uncalibrated, which is why the
    # bug looked position-specific rather than like a global miscalibration.
    for position in ("11", "12", "01"):
        target = targets[position]
        resolved = nearest_clock_position(
            target.yaw_deg,
            target.pitch_deg + neutral_pitch,
            yaw_range_deg=settings.yaw_range_deg,
            pitch_range_deg=settings.pitch_range_deg,
        )
        assert resolved == position
