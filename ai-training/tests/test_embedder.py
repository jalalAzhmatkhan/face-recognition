"""StubEmbedder determinism (TR-03) — no torch/cv2 needed, just numpy.

Also covers `AdaFaceEmbedder` (TR-06) preprocessing math and the
actionable-error path when weights are missing — both pure-Python/numpy,
no real checkpoint needed. `test_adaface_net.py` covers the vendored
architecture's forward-pass shape separately.
"""

import numpy as np
import pytest

from ai_training.config import EmbedderSettings, Settings
from ai_training.embedding.embedder import (
    EMBEDDING_DIM,
    AdaFaceEmbedder,
    StubEmbedder,
    build_embedder,
    preprocess_bgr_crop,
)


def test_stub_embedder_is_deterministic() -> None:
    embedder = StubEmbedder()
    crop = np.arange(112 * 112 * 3, dtype=np.uint8).reshape(112, 112, 3)
    first = embedder.embed(crop)
    second = embedder.embed(crop)
    assert first == second


def test_stub_embedder_differs_across_inputs() -> None:
    embedder = StubEmbedder()
    crop_a = np.zeros((112, 112, 3), dtype=np.uint8)
    crop_b = np.ones((112, 112, 3), dtype=np.uint8)
    assert embedder.embed(crop_a) != embedder.embed(crop_b)


def test_stub_embedder_is_l2_normalized_and_right_shape() -> None:
    embedder = StubEmbedder()
    crop = np.full((112, 112, 3), 200, dtype=np.uint8)
    vector = embedder.embed(crop)
    assert len(vector) == EMBEDDING_DIM
    norm = float(np.linalg.norm(np.asarray(vector)))
    assert abs(norm - 1.0) < 1e-6


def test_stub_embedder_with_quality_reports_no_feature_norm() -> None:
    # EC-IN-02 (TSD-edge-cases.md D-3 C-3): StubEmbedder has no real quality
    # signal -- `embed_with_quality` must report `feature_norm=None` (never
    # a fabricated number), and the embedding itself must be identical to
    # plain `embed()`.
    embedder = StubEmbedder()
    crop = np.arange(112 * 112 * 3, dtype=np.uint8).reshape(112, 112, 3)
    vector, feature_norm = embedder.embed_with_quality(crop)
    assert vector == embedder.embed(crop)
    assert feature_norm is None


def test_build_embedder_defaults_to_stub() -> None:
    settings = Settings(_env_file=None)
    embedder = build_embedder(settings)
    assert isinstance(embedder, StubEmbedder)
    assert embedder.model_version == "stub-v1"


def test_build_embedder_stub_version_configurable() -> None:
    settings = Settings(
        _env_file=None, embedder=EmbedderSettings(backend="stub", stub_version="stub-v2")
    )
    embedder = build_embedder(settings)
    assert embedder.model_version == "stub-v2"


def test_build_embedder_selects_adaface_backend() -> None:
    settings = Settings(_env_file=None, embedder=EmbedderSettings(backend="adaface"))
    embedder = build_embedder(settings)
    assert isinstance(embedder, AdaFaceEmbedder)


def test_preprocess_bgr_crop_shape_and_range() -> None:
    crop = np.zeros((112, 112, 3), dtype=np.uint8)
    crop[..., 0] = 255  # max value on one channel
    tensor = preprocess_bgr_crop(crop)
    assert tensor.shape == (1, 3, 112, 112)
    assert tensor.dtype == np.float32
    # (0/255 - 0.5)/0.5 == -1.0 ; (255/255 - 0.5)/0.5 == 1.0
    assert np.isclose(tensor.min(), -1.0)
    assert np.isclose(tensor.max(), 1.0)


def test_preprocess_bgr_crop_rejects_wrong_shape() -> None:
    with pytest.raises(ValueError, match="expected"):
        preprocess_bgr_crop(np.zeros((64, 64, 3), dtype=np.uint8))


def test_adaface_embedder_model_version_is_stable() -> None:
    settings = Settings(
        _env_file=None, embedder=EmbedderSettings(backend="adaface", adaface_arch="ir_101")
    )
    embedder = AdaFaceEmbedder(settings)
    assert embedder.model_version == "adaface-ir101-webface12m"
    # Calling it twice must yield the identical string (DB stability), not
    # e.g. a hash that changes across runs/instances.
    assert embedder.model_version == AdaFaceEmbedder(settings).model_version


def test_adaface_embedder_raises_actionable_error_when_weights_missing(tmp_path) -> None:
    # This test is specifically about the "torch IS available but the
    # checkpoint file is absent" path -- on base CI (no `ml` extra, no
    # torch), `_get_model()` raises a DIFFERENT (still actionable) error
    # first ("requires the 'ml' extra"). That path is covered instead by
    # test_adaface_embedder_raises_actionable_error_when_ml_extra_missing
    # below, which runs unconditionally.
    pytest.importorskip("torch")
    missing_path = tmp_path / "does-not-exist.ckpt"
    settings = Settings(
        _env_file=None,
        embedder=EmbedderSettings(
            backend="adaface", adaface_arch="ir_101", adaface_weights_path=str(missing_path)
        ),
    )
    embedder = AdaFaceEmbedder(settings)
    crop = np.zeros((112, 112, 3), dtype=np.uint8)
    with pytest.raises(RuntimeError) as exc_info:
        embedder.embed(crop)
    message = str(exc_info.value)
    assert str(missing_path) in message
    assert "download-adaface-weights" in message


def test_adaface_embedder_raises_actionable_error_when_ml_extra_missing() -> None:
    """Complements the test above for base CI (no `ml` extra, no torch
    installed at all): `embed()` must still fail with an actionable
    `RuntimeError` naming the missing extra, never a raw
    `ModuleNotFoundError` leaking out of an unguarded `import torch`."""
    try:
        import torch  # noqa: F401

        pytest.skip("torch is installed in this environment; see the test above instead")
    except ImportError:
        pass

    settings = Settings(_env_file=None, embedder=EmbedderSettings(backend="adaface"))
    embedder = AdaFaceEmbedder(settings)
    crop = np.zeros((112, 112, 3), dtype=np.uint8)
    with pytest.raises(RuntimeError, match="ml.*extra"):
        embedder.embed(crop)


def test_adaface_embedder_embed_delegates_to_embed_with_quality_error_path() -> None:
    """EC-IN-02: `embed()` was refactored to call `embed_with_quality()[0]`
    -- confirm the SAME actionable error still surfaces through `embed()`
    on base CI (no torch), i.e. the refactor didn't change error-path
    behavior at all."""
    try:
        import torch  # noqa: F401

        pytest.skip("torch is installed in this environment")
    except ImportError:
        pass

    settings = Settings(_env_file=None, embedder=EmbedderSettings(backend="adaface"))
    embedder = AdaFaceEmbedder(settings)
    crop = np.zeros((112, 112, 3), dtype=np.uint8)
    with pytest.raises(RuntimeError, match="ml.*extra"):
        embedder.embed_with_quality(crop)
