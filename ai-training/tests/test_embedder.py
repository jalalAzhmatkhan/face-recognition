"""StubEmbedder determinism (TR-03) — no torch/cv2 needed, just numpy."""

import numpy as np

from ai_training.config import EmbedderSettings, Settings
from ai_training.embedding.embedder import EMBEDDING_DIM, StubEmbedder, build_embedder


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
