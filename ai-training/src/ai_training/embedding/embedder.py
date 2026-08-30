"""Embedder interface + implementations (TR-03/TR-06).

Mirrors the `ModelLoader`/`StubModelLoader`/`MLflowModelLoader` pattern
established by `ai-inference/src/ai_inference/models/loader.py` (IN-01):
an abstract interface the pipeline depends on, a deterministic stub used
everywhere in tests/CI, and a real implementation (`AdaFaceEmbedder`,
landed TR-06) that lazy-loads a procured pretrained checkpoint.

**`StubEmbedder` is still the DEFAULT backend** (`EmbedderSettings.backend
== "stub"`) and remains what test/CI environments use — it carries NO face
recognition signal, it exists only so the enrollment plumbing (sampling ->
alignment -> embed -> pgvector upsert) can be built and tested without a
~250MB checkpoint on disk. `AdaFaceEmbedder` is real (not a skeleton) as of
TR-06, but is opt-in via `TRN_EMBEDDER__BACKEND=adaface` because it
requires the `ml` extra AND a downloaded weight file (see
`ai_training.download_adaface_weights`).
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

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


# AdaFace's own preprocessing (`inference.py::to_input`) normalizes pixel
# values from [0, 255] to [-1, 1] via `(x/255 - 0.5) / 0.5`, matching the
# symmetric input range the model was trained on (NOT the more common
# ImageNet mean/std normalization — AdaFace/ArcFace-family models use this
# simpler symmetric scaling).
_PIXEL_SCALE = 255.0
_PIXEL_MEAN = 0.5
_PIXEL_STD = 0.5


def preprocess_bgr_crop(aligned_crop: Any) -> np.ndarray:
    """Turn one aligned 112x112x3 uint8 crop into the `(1, 3, 112, 112)`
    float32 tensor-shaped array AdaFace's backbone expects.

    **Channel-order finding (verified against this repo's own pipeline,
    documented here because a silent mismatch here would poison every
    embedding without raising any error)**: upstream AdaFace's
    `inference.py::to_input` takes a PIL RGB image and explicitly flips it
    to BGR (`np_img[:, :, ::-1]`) before normalizing — i.e. the trained
    model's actual input convention is BGR, the RGB->BGR flip is just
    upstream's way of getting there from a PIL-loaded (RGB) image.

    This project's aligned crops never go through PIL. Tracing the source:
    `ai_training.quality.pipeline`'s frame decode uses `cv2.VideoCapture`
    (see its module docstring / `_decode_video` — OpenCV's `VideoCapture`
    always yields BGR ndarrays, never RGB), those BGR frames flow untouched
    through `quality.pose.detect_face_and_landmarks` (which explicitly
    flips BGR->RGB *only* for its own internal mediapipe call, and returns
    landmarks, not pixels) and into `embedding.alignment.align_face`, whose
    `cv2.warpAffine` call preserves whatever channel order its input frame
    already has. So the crop arriving here is BGR — the SAME convention
    AdaFace's backbone expects. Net effect: **no RGB<->BGR flip is needed
    in this function.** (If this project's decode path ever changes to
    produce RGB frames — e.g. a PIL/PyAV-based decoder swap — this function
    must add the flip back, and this docstring must be updated to match.)
    """
    arr = np.asarray(aligned_crop)
    if arr.shape != (112, 112, 3):
        raise ValueError(f"preprocess_bgr_crop: expected (112, 112, 3), got {arr.shape}")
    normalized = (arr.astype(np.float32) / _PIXEL_SCALE - _PIXEL_MEAN) / _PIXEL_STD
    chw = np.transpose(normalized, (2, 0, 1))  # (H, W, C) -> (C, H, W)
    return np.expand_dims(chw, axis=0)  # -> (1, C, H, W)


class AdaFaceEmbedder(EmbedderInterface):
    """Real AdaFace IR-50/IR-101 embedder (TR-06).

    **Procurement / licensing** (recorded 2026-08-30 in
    `documentation/research/recommendations.md`): weights are the
    upstream AdaFace IR-101 (`num_layers=100`) checkpoint trained on
    WebFace12M — recommendations.md §2's pick "untuk akurasi maksimal".
    The user has knowingly accepted the non-commercial license risk this
    carries, on the basis that this application is internal-only and not
    sold. Download with:

        uv run ai-training download-adaface-weights

    (or `uv run python -m ai_training.download_adaface_weights`), which
    fetches the checkpoint from upstream's Google Drive distribution (file
    id hardcoded in `ai_training.download_adaface_weights`) and normalizes
    it into a bare backbone `state_dict` at
    `ai-training/models/adaface_ir101_webface12m.ckpt` (gitignored —
    `*.ckpt` — never committed).

    Lazy-loads the model once (on first `embed()` call) and reuses it for
    the lifetime of this instance — construction itself (`__init__`) does
    NOT touch disk or import torch, so `AdaFaceEmbedder(settings)` stays
    cheap even when the backend is unused (mirrors
    `ai_inference.models.loader.MLflowModelLoader`'s lazy-import shape).
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model: Any = None  # lazy-loaded torch.nn.Module, see _get_model()

    @property
    def model_version(self) -> str:
        """Stable across runs (NOT a checkpoint hash) — this is what gets
        written to `face_embeddings.model_version`, and must stay constant
        so re-runs against the same weights are recognized as the same
        model rather than triggering spurious re-embedding."""
        arch = self._settings.embedder.adaface_arch
        return f"adaface-{arch.replace('_', '')}-webface12m"

    def _weights_path(self) -> Path:
        configured = self._settings.embedder.adaface_weights_path
        if configured:
            return Path(configured)
        from ai_training.download_adaface_weights import default_weights_path

        return default_weights_path(self._settings.embedder.adaface_arch)

    def _get_model(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            import torch
        except ImportError as exc:  # pragma: no cover - depends on extras
            raise RuntimeError(
                "AdaFaceEmbedder requires the 'ml' extra (uv sync --extra ml): torch."
            ) from exc

        from ai_training.embedding import adaface_net

        weights_path = self._weights_path()
        if not weights_path.is_file():
            raise RuntimeError(
                f"AdaFace weights not found at '{weights_path}'. Download them with: "
                "uv run ai-training download-adaface-weights "
                f"--arch {self._settings.embedder.adaface_arch} "
                "(requires the 'ml' extra: uv sync --extra ml). See "
                "ai_training.embedding.embedder.AdaFaceEmbedder's docstring for the licensing "
                "decision behind these weights."
            )

        model = adaface_net.build_model(self._settings.embedder.adaface_arch)
        state_dict = torch.load(weights_path, map_location="cpu")
        model.load_state_dict(state_dict)
        model.eval()
        self._model = model
        return model

    def embed(self, aligned_crop: Any) -> list[float]:
        import torch

        model = self._get_model()
        input_array = preprocess_bgr_crop(aligned_crop)
        input_tensor = torch.from_numpy(input_array)
        with torch.no_grad():
            output, _norm = model(input_tensor)
        # `output` is ALREADY L2-normalized by the backbone (see
        # `adaface_net.Backbone.forward`: `output = x / norm`) — no
        # re-normalization needed or wanted here.
        return [float(v) for v in output[0].tolist()]


def build_embedder(settings: Settings) -> EmbedderInterface:
    """Factory selecting the embedder backend from configuration
    (`TRN_EMBEDDER__BACKEND`, default `"stub"`)."""
    if settings.embedder.backend == "adaface":
        return AdaFaceEmbedder(settings)
    return StubEmbedder(version=settings.embedder.stub_version)
