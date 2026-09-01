"""EC-IN-03 (TSD-edge-cases.md C-2/OQ-4): `ai_inference.pipeline.mask_sunglasses`
-- the ONNX Runtime serving wrapper.

Needs the `ml` extra (`onnxruntime`, plus `ai-training[ml]`'s `torch`/`onnx`
to build a real exported model to test against). Skipped entirely on base
CI, same convention as this project's other `ml`-extra test modules.

Exercises the ACTUAL onnxruntime session against a real (untrained, random-
weight) exported model -- both the mechanical round trip and the measured
per-crop latency are real numbers; per the training-side module's own
caveat, none of this says anything about classification ACCURACY (that
needs a real trained checkpoint + real data, not available in this
sandbox).
"""

from __future__ import annotations

import time

import numpy as np
import pytest

onnxruntime = pytest.importorskip("onnxruntime")
torch = pytest.importorskip("torch")

from ai_inference.pipeline.mask_sunglasses import (  # noqa: E402
    LABEL_NAMES,
    get_classifier,
    load_classifier,
)


@pytest.fixture
def exported_model_path(tmp_path):
    """A REAL exported ONNX model (untrained/random weights) from
    `ai_training.classifiers.mask_sunglasses` -- this is exactly the
    artifact `ai_training.classifiers.mask_sunglasses.export_onnx` produces
    and the real serving path would load; using a random-weight model here
    is legitimate for testing the WRAPPER's plumbing/latency (see this
    module's own docstring) even though it says nothing about accuracy.
    """
    from ai_training.classifiers.mask_sunglasses import DEFAULT_IMG_SIZE, build_model, export_onnx

    model = build_model(img_size=DEFAULT_IMG_SIZE)
    path = tmp_path / "mask_sunglasses.onnx"
    export_onnx(model, path, img_size=DEFAULT_IMG_SIZE)
    return str(path), DEFAULT_IMG_SIZE


def test_load_classifier_returns_none_for_empty_path() -> None:
    assert load_classifier("") is None


def test_load_classifier_returns_none_for_missing_file(tmp_path) -> None:
    missing = tmp_path / "does_not_exist.onnx"
    assert load_classifier(str(missing)) is None


def test_load_classifier_returns_none_for_corrupt_file(tmp_path) -> None:
    corrupt = tmp_path / "corrupt.onnx"
    corrupt.write_bytes(b"not a real onnx file")
    assert load_classifier(str(corrupt)) is None


def test_load_classifier_succeeds_for_real_exported_model(exported_model_path) -> None:
    path, img_size = exported_model_path

    classifier = load_classifier(path, img_size=img_size)

    assert classifier is not None
    assert classifier.img_size == img_size


def test_classify_returns_two_bools_for_synthetic_crop(exported_model_path) -> None:
    path, img_size = exported_model_path
    classifier = load_classifier(path, img_size=img_size)
    assert classifier is not None
    crop = np.random.default_rng(0).integers(
        0, 255, size=(120, 100, 3), dtype=np.uint8
    )  # arbitrary crop size -- wrapper must resize internally

    result = classifier.classify(crop)

    assert result is not None
    masked, sunglasses = result
    assert isinstance(masked, bool)
    assert isinstance(sunglasses, bool)


def test_classify_returns_none_on_empty_crop_without_raising(exported_model_path) -> None:
    path, img_size = exported_model_path
    classifier = load_classifier(path, img_size=img_size)
    assert classifier is not None
    empty_crop = np.zeros((0, 0, 3), dtype=np.uint8)

    result = classifier.classify(empty_crop)

    assert result is None  # never raises -- caller falls back to the heuristic


def test_get_classifier_singleton_falls_back_to_none_by_default(monkeypatch) -> None:
    # Default `Settings.mask_sunglasses_model_path` is "" (task brief: no
    # model shipped in this sandbox/repo yet) -- `get_classifier()` must
    # degrade to `None`, never raise, so `recognize.py`'s call site is
    # exercised end-to-end even with zero model artifacts present.
    from ai_inference.config import get_settings

    get_settings.cache_clear()
    get_classifier.cache_clear()
    monkeypatch.delenv("INF_MASK_SUNGLASSES_MODEL_PATH", raising=False)

    try:
        assert get_classifier() is None
    finally:
        get_classifier.cache_clear()
        get_settings.cache_clear()


def test_get_classifier_singleton_loads_configured_model(exported_model_path, monkeypatch) -> None:
    path, img_size = exported_model_path
    from ai_inference.config import get_settings

    monkeypatch.setenv("INF_MASK_SUNGLASSES_MODEL_PATH", path)
    monkeypatch.setenv("INF_MASK_SUNGLASSES_IMG_SIZE", str(img_size))
    get_settings.cache_clear()
    get_classifier.cache_clear()

    try:
        classifier = get_classifier()
        assert classifier is not None
        # Second call must be the SAME cached object (singleton, no reload).
        assert get_classifier() is classifier
    finally:
        get_classifier.cache_clear()
        get_settings.cache_clear()


def test_single_thread_session_option_is_applied(exported_model_path) -> None:
    """TSD-edge-cases.md C-2: "ONNX Runtime single-thread" -- assert the
    loaded session was actually configured that way, not just that
    inference happens to work."""
    path, img_size = exported_model_path
    classifier = load_classifier(path, img_size=img_size)
    assert classifier is not None
    assert classifier.session.get_session_options().intra_op_num_threads == 1


def test_classify_latency_under_3ms_budget(exported_model_path) -> None:
    """TSD-edge-cases.md C-2 acceptance criterion: <=3ms CPU per crop.
    Measured against the REAL serving wrapper (preprocessing + ONNX
    Runtime session.run), on an untrained model -- legitimate for a
    latency claim (architecture + runtime cost, not weights, drive
    latency), NOT an accuracy claim (see module docstring)."""
    path, img_size = exported_model_path
    classifier = load_classifier(path, img_size=img_size)
    assert classifier is not None
    crop = np.random.default_rng(1).integers(0, 255, size=(96, 96, 3), dtype=np.uint8)

    # Warm-up run (one-time graph optimization cost a long-running service
    # never re-pays per request).
    classifier.classify(crop)

    n_runs = 50
    start = time.perf_counter()
    for _ in range(n_runs):
        classifier.classify(crop)
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    per_crop_ms = elapsed_ms / n_runs
    assert per_crop_ms <= 3.0, f"per-crop latency {per_crop_ms:.3f}ms exceeds 3ms budget"


def test_label_names_match_training_side_order() -> None:
    from ai_training.classifiers.mask_sunglasses import LABEL_NAMES as TRAIN_LABEL_NAMES

    assert LABEL_NAMES == TRAIN_LABEL_NAMES
