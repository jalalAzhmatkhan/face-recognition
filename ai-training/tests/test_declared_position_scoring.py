"""`_evaluate_frame`'s `declared_position` — scoring a sweep frame against
the clock position it was CAPTURED FOR rather than the one it lands
nearest.

Why this is worth its own file: `nearest_clock_position` has no radius
gate, so on the video path every frame is filed under SOME position no
matter how far off it is. A subject who drifts from 5 o'clock toward 4
therefore has that frame quietly counted as 4 — 4 passes, 5 stays uncovered
with a `no_face_detected` it never earned, and the operator is told to redo
a position that was actually attempted. With the position declared, the
same drift is scored against 5 and comes back as `pose_out_of_range`.

The landmark detector and pose estimator are monkeypatched: these tests
pin the ROUTING decision, not the estimators.
"""

from __future__ import annotations

import pytest

from ai_training.config import QCSettings
from ai_training.quality import pipeline as qc_pipeline
from ai_training.quality.pipeline import _evaluate_frame
from ai_training.quality.pose import clock_position_targets


@pytest.fixture
def settings() -> QCSettings:
    return QCSettings()


class _Frame:
    """Stands in for the numpy array; only `.shape` is read."""

    shape = (720, 1280, 3)


@pytest.fixture
def pose_at(monkeypatch, settings):
    """Force the estimator to report an exact (yaw, pitch), and make every
    non-pose quality metric pass so `reasons` isolates pose alone."""

    def _install(yaw: float, pitch: float) -> None:
        monkeypatch.setattr(
            qc_pipeline,
            "detect_face_and_landmarks",
            lambda frame, model_path=None: _Detection(),
        )
        monkeypatch.setattr(
            qc_pipeline,
            "estimate_pose_from_landmarks",
            lambda detection, size: (yaw, pitch, 0.0),
        )
        monkeypatch.setattr(qc_pipeline.qmetrics, "blur_score", lambda frame: 500.0)
        monkeypatch.setattr(qc_pipeline.qmetrics, "brightness_score", lambda frame: 128.0)
        monkeypatch.setattr(
            qc_pipeline.qmetrics, "face_size_ratio", lambda bbox_wh, size: 0.5
        )

    return _install


class _Detection:
    bbox_wh = (300, 300)


def _target(position: str, settings: QCSettings):
    return clock_position_targets(settings.yaw_range_deg, settings.pitch_range_deg)[position]


def test_a_frame_dead_on_its_declared_target_passes(settings, pose_at) -> None:
    target = _target("05", settings)
    pose_at(target.yaw_deg, target.pitch_deg)

    result = _evaluate_frame(_Frame(), settings, None, declared_position="05")

    assert result is not None
    assert result.position == "05"
    assert result.passed is True


def test_a_frame_that_drifted_to_a_neighbour_fails_its_declared_position(
    settings, pose_at
) -> None:
    # Pose is exactly 4 o'clock, but the client captured it FOR 5.
    four = _target("04", settings)
    pose_at(four.yaw_deg, four.pitch_deg)

    result = _evaluate_frame(_Frame(), settings, None, declared_position="05")

    assert result is not None
    # Filed under 05 (what was asked for), and honestly marked as missing it
    # -- NOT silently relabelled as a passing 04.
    assert result.position == "05"
    assert result.passed is False
    assert "pose_out_of_range" in result.reasons


def test_the_video_path_still_relabels_to_the_nearest_position(settings, pose_at) -> None:
    """Regression guard on the unchanged behaviour: with no declared
    position (legacy video sessions), the frame is still filed under
    whichever target it lands nearest."""
    four = _target("04", settings)
    pose_at(four.yaw_deg, four.pitch_deg)

    result = _evaluate_frame(_Frame(), settings, None)

    assert result is not None
    assert result.position == "04"
    assert result.passed is True


def test_declared_position_is_honoured_at_every_point_on_the_dial(settings, pose_at) -> None:
    for i in range(1, 13):
        position = f"{i:02d}"
        target = _target(position, settings)
        pose_at(target.yaw_deg, target.pitch_deg)

        result = _evaluate_frame(_Frame(), settings, None, declared_position=position)

        assert result is not None, position
        assert result.position == position
        assert result.passed is True, f"{position} failed: {result.reasons}"


def test_the_bottom_half_is_reachable_once_the_neutral_baseline_is_applied(
    settings, pose_at
) -> None:
    """The phase-1 bug, re-checked on the photo path: a subject whose
    resting pose reads +24.3 pitch is looking at 6 o'clock when the RAW
    estimate is still positive. Without calibration that frame fails; with
    it, it passes."""
    six = _target("06", settings)
    raw_pitch = six.pitch_deg + 24.3
    pose_at(six.yaw_deg, raw_pitch)

    uncalibrated = _evaluate_frame(_Frame(), settings, None, declared_position="06")
    calibrated = _evaluate_frame(_Frame(), settings, (0.0, 24.3), declared_position="06")

    assert uncalibrated is not None and uncalibrated.passed is False
    assert "pose_out_of_range" in uncalibrated.reasons
    assert calibrated is not None and calibrated.passed is True


def test_a_frame_with_no_detected_face_is_still_dropped(settings, monkeypatch) -> None:
    monkeypatch.setattr(
        qc_pipeline, "detect_face_and_landmarks", lambda frame, model_path=None: None
    )

    assert _evaluate_frame(_Frame(), settings, None, declared_position="05") is None


def test_non_pose_quality_failures_still_apply_on_the_photo_path(
    settings, pose_at, monkeypatch
) -> None:
    """Declaring a position must not become a way to bypass the blur /
    lighting / face-size gates."""
    target = _target("05", settings)
    pose_at(target.yaw_deg, target.pitch_deg)
    monkeypatch.setattr(qc_pipeline.qmetrics, "blur_score", lambda frame: 1.0)

    result = _evaluate_frame(_Frame(), settings, None, declared_position="05")

    assert result is not None
    assert result.passed is False
    assert "blurry" in result.reasons
