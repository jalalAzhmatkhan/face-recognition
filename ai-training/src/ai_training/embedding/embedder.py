"""Embedder interface + implementations (TR-03).

Mirrors the `ModelLoader`/`StubModelLoader`/`MLflowModelLoader` pattern
established by `ai-inference/src/ai_inference/models/loader.py` (IN-01):
an abstract interface the pipeline depends on, a deterministic stub used
everywhere today, and a real-implementation skeleton that raises
`NotImplementedError` until the underlying pretrained model is procured.

**Explicit placeholder notice**: `StubEmbedder` does NOT perform real face
recognition. AdaFace pretrained weights (the ratified recommendation, see
`documentation/research/recommendations.md` §2) have not been downloaded or
licensed for this task — that is a separate procurement decision. Nothing
in this module should be read as "embeddings are ready for production
matching"; it exists so the enrollment plumbing (sampling -> alignment ->
embed -> pgvector upsert) can be built, tested, and wired end-to-end today,
ready to swap in `AdaFaceEmbedder` later with no change to callers.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ai_training.config import Settings

EMBEDDING_DIM = 512


class EmbedderInterface(ABC):
    """The pipeline depends on this, never on a concrete embedder class."""

    @property
    @abstractmethod
    def model_version(self) -> str:
        """Version string stored on `face_embeddings.model_version`."""

    @abstractmethod
    def embed(self, aligned_crop: Any) -> list[float]:
        """Embed one aligned 112x112 face crop into an L2-normalized
        `EMBEDDING_DIM`-d vector."""


class StubEmbedder(EmbedderInterface):
    """Deterministic placeholder — see module docstring. Produces an
    L2-normalized pseudo-embedding seeded from a hash of the input pixels:
    the SAME input always yields the SAME output (useful for idempotent
    re-runs and tests), and different inputs yield different (effectively
    uncorrelated) outputs. This carries NO face-recognition signal — it is
    not fit for measuring Recall/F1/Precision against real faces.
    """

    def __init__(self, version: str = "stub-v1") -> None:
        self._version = version

    @property
    def model_version(self) -> str:
        return self._version

    def embed(self, aligned_crop: Any) -> list[float]:
        import numpy as np

        arr = np.asarray(aligned_crop)
        digest = hashlib.sha256(arr.tobytes()).digest()
        seed = int.from_bytes(digest[:8], "big")
        rng = np.random.default_rng(seed)
        vector = rng.normal(size=EMBEDDING_DIM)
        norm = np.linalg.norm(vector)
        if norm > 0:
            vector = vector / norm
        return [float(x) for x in vector]


class AdaFaceEmbedder(EmbedderInterface):
    """TODO(procurement): real AdaFace IR-50/IR-101 embedder.

    Blocked on the licensing/procurement decision described in
    `documentation/research/recommendations.md` §2 (SCRFD/AdaFace
    pretrained weights). Do NOT implement/download weights for this class
    as part of this task — it is intentionally left as a skeleton, mirroring
    `ai_inference.models.loader.MLflowModelLoader`'s
    "lazy-import, raise NotImplementedError" shape.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def model_version(self) -> str:
        raise NotImplementedError("AdaFaceEmbedder lands after model procurement.")

    def embed(self, aligned_crop: Any) -> list[float]:
        try:
            import torch  # noqa: F401
        except ImportError as exc:  # pragma: no cover - depends on extras
            raise RuntimeError(
                "AdaFaceEmbedder requires the 'ml' extra (uv sync --extra ml)."
            ) from exc
        raise NotImplementedError(
            "AdaFaceEmbedder lands once AdaFace weights are procured "
            "(see documentation/research/recommendations.md)."
        )


def build_embedder(settings: Settings) -> EmbedderInterface:
    """Factory selecting the embedder backend from configuration
    (`TRN_EMBEDDER__BACKEND`, default `"stub"`)."""
    if settings.embedder.backend == "adaface":
        return AdaFaceEmbedder(settings)
    return StubEmbedder(version=settings.embedder.stub_version)
