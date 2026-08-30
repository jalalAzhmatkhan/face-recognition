"""Pure-math unit tests for the ASM-03-corrected clock-position <-> (yaw,
pitch) mapping — no cv2/mediapipe needed."""

import pytest

from ai_training.quality.pose import (
    CLOCK_POSITIONS,
    clock_position_targets,
    nearest_clock_position,
)

YAW_RANGE = 35.0
PITCH_RANGE = 25.0


def test_clock_positions_are_twelve_zero_padded_labels() -> None:
    assert CLOCK_POSITIONS == tuple(f"{i:02d}" for i in range(1, 13))


def test_clock_position_targets_cardinal_points() -> None:
    targets = clock_position_targets(YAW_RANGE, PITCH_RANGE)
    # 12 o'clock: head tilted up, no yaw.
    assert targets["12"].yaw_deg == pytest.approx(0.0, abs=1e-6)
    assert targets["12"].pitch_deg == pytest.approx(PITCH_RANGE)
    # 3 o'clock: head turned right, no pitch change.
    assert targets["03"].yaw_deg == pytest.approx(YAW_RANGE)
    assert targets["03"].pitch_deg == pytest.approx(0.0, abs=1e-6)
    # 6 o'clock: head tilted down.
    assert targets["06"].yaw_deg == pytest.approx(0.0, abs=1e-6)
    assert targets["06"].pitch_deg == pytest.approx(-PITCH_RANGE)
    # 9 o'clock: head turned left.
    assert targets["09"].yaw_deg == pytest.approx(-YAW_RANGE)
    assert targets["09"].pitch_deg == pytest.approx(0.0, abs=1e-6)


@pytest.mark.parametrize(
    ("yaw", "pitch", "expected"),
    [
        (0.0, PITCH_RANGE, "12"),
        (YAW_RANGE, 0.0, "03"),
        (0.0, -PITCH_RANGE, "06"),
        (-YAW_RANGE, 0.0, "09"),
    ],
)
def test_nearest_clock_position_cardinal_points(yaw: float, pitch: float, expected: str) -> None:
    assert (
        nearest_clock_position(yaw, pitch, yaw_range_deg=YAW_RANGE, pitch_range_deg=PITCH_RANGE)
        == expected
    )


def test_nearest_clock_position_realistic_range_not_full_profile() -> None:
    # ASM-03 correction: the achievable yaw/pitch envelope is a realistic
    # head turn (~30-45deg yaw), not a 90deg full-profile view. A pose at
    # the configured max yaw should map cleanly onto its target sector.
    targets = clock_position_targets(YAW_RANGE, PITCH_RANGE)
    for position, target in targets.items():
        assert (
            nearest_clock_position(
                target.yaw_deg,
                target.pitch_deg,
                yaw_range_deg=YAW_RANGE,
                pitch_range_deg=PITCH_RANGE,
            )
            == position
        )
