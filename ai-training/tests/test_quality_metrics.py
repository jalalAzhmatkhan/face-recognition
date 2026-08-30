"""Pure-numpy unit tests for TR-02 quality metrics — no cv2/mediapipe needed."""

import numpy as np

from ai_training.quality.metrics import blur_score, brightness_score, face_size_ratio


def test_blur_score_higher_for_sharp_image() -> None:
    rng = np.random.default_rng(42)
    sharp = rng.integers(0, 256, size=(64, 64), dtype=np.uint8)  # high-frequency noise = "sharp"
    blurred = np.full((64, 64), 128, dtype=np.uint8)  # uniform = no edges at all
    assert blur_score(sharp) > blur_score(blurred)
    assert blur_score(blurred) == 0.0


def test_blur_score_handles_color_image() -> None:
    rng = np.random.default_rng(7)
    color = rng.integers(0, 256, size=(32, 32, 3), dtype=np.uint8)
    score = blur_score(color)
    assert score > 0.0


def test_brightness_score_dark_vs_bright() -> None:
    dark = np.zeros((16, 16), dtype=np.uint8)
    bright = np.full((16, 16), 255, dtype=np.uint8)
    assert brightness_score(dark) == 0.0
    assert brightness_score(bright) == 255.0


def test_face_size_ratio() -> None:
    assert face_size_ratio((100.0, 100.0), (1000.0, 1000.0)) == 0.01
    assert face_size_ratio((0.0, 0.0), (0.0, 0.0)) == 0.0
