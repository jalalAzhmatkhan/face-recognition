"""`StubLivenessDetector` determinism + `build_liveness_detector` backend
selection + actionable-error paths for `MiniFASNetLivenessDetector` (IN-04).
Mirrors `test_embedder.py`'s structure for `StubEmbedder`/`AdaFaceEmbedder`.
"""

import numpy as np
import pytest

from ai_training.config import LivenessSettings, Settings
from ai_training.liveness.detector import (
    MiniFASNetLivenessDetector,
    StubLivenessDetector,
    build_liveness_detector,
)

_FRAME = np.arange(100 * 100 * 3, dtype=np.uint8).reshape(100, 100, 3)


def test_stub_liveness_detector_is_deterministic() -> None:
    detector = StubLivenessDetector()
    first = detector.score(_FRAME, bbox_xy=(10, 10), bbox_wh=(40, 40))
    second = detector.score(_FRAME, bbox_xy=(10, 10), bbox_wh=(40, 40))
    assert first == second


def test_stub_liveness_detector_differs_across_inputs() -> None:
    detector = StubLivenessDetector()
    frame_a = np.zeros((100, 100, 3), dtype=np.uint8)
    frame_b = np.ones((100, 100, 3), dtype=np.uint8)
    score_a = detector.score(frame_a, bbox_xy=(10, 10), bbox_wh=(40, 40))
    score_b = detector.score(frame_b, bbox_xy=(10, 10), bbox_wh=(40, 40))
    assert score_a != score_b


def test_stub_liveness_detector_score_in_unit_range() -> None:
    detector = StubLivenessDetector()
    score = detector.score(_FRAME, bbox_xy=(10, 10), bbox_wh=(40, 40))
    assert 0.0 <= score <= 1.0


def test_build_liveness_detector_defaults_to_stub() -> None:
    settings = Settings(_env_file=None)
    detector = build_liveness_detector(settings)
    assert isinstance(detector, StubLivenessDetector)
    assert detector.model_version == "stub-v1"


def test_build_liveness_detector_selects_minifasnet_backend() -> None:
    settings = Settings(_env_file=None, liveness=LivenessSettings(backend="minifasnet"))
    detector = build_liveness_detector(settings)
    assert isinstance(detector, MiniFASNetLivenessDetector)
    assert detector.model_version == "minifasnet-v2-2.7-v1se-4.0-ensemble"


def test_minifasnet_detector_raises_actionable_error_when_weights_missing(tmp_path) -> None:
    pytest.importorskip("torch")
    missing_v2 = tmp_path / "does-not-exist-v2.pth"
    missing_v1se = tmp_path / "does-not-exist-v1se.pth"
    settings = Settings(
        _env_file=None,
        liveness=LivenessSettings(
            backend="minifasnet",
            minifasnet_v2_weights_path=str(missing_v2),
            minifasnet_v1se_weights_path=str(missing_v1se),
        ),
    )
    detector = MiniFASNetLivenessDetector(settings)
    with pytest.raises(RuntimeError) as exc_info:
        detector.score(_FRAME, bbox_xy=(10, 10), bbox_wh=(40, 40))
    message = str(exc_info.value)
    assert str(missing_v2) in message


def test_minifasnet_detector_raises_actionable_error_when_ml_extra_missing() -> None:
    """Complements the test above for base CI (no `ml` extra, no torch
    installed at all): `score()` must fail with an actionable `RuntimeError`
    naming the missing extra, never a raw `ModuleNotFoundError`."""
    try:
        import torch  # noqa: F401

        pytest.skip("torch is installed in this environment; see the test above instead")
    except ImportError:
        pass

    settings = Settings(_env_file=None, liveness=LivenessSettings(backend="minifasnet"))
    detector = MiniFASNetLivenessDetector(settings)
    with pytest.raises(RuntimeError, match="ml.*extra"):
        detector.score(_FRAME, bbox_xy=(10, 10), bbox_wh=(40, 40))
