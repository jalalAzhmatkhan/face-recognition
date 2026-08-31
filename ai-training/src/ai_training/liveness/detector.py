"""Liveness detector interface + implementations (IN-04).

Mirrors the `EmbedderInterface`/`StubEmbedder`/`AdaFaceEmbedder` pattern in
`ai_training.embedding.embedder`: an abstract interface the inference
pipeline depends on, a deterministic stub used everywhere in tests/CI, and
a real implementation (`MiniFASNetLivenessDetector`) that lazy-loads two
committed pretrained checkpoints.

`StubLivenessDetector` is still the DEFAULT backend (`LivenessSettings.backend
== "stub"`) — real anti-spoofing needs the `ml` extra (torch + opencv) and
the two `.pth` files this module loads.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from ai_training.config import Settings

# MiniFASNet input size (both variants) and the two scale factors upstream's
# `anti_spoof_predict.py` pairs with each checkpoint. `conv6_kernel` for BOTH
# models must be `get_kernel(80, 80)` -- see module docstring math below --
# NOT the architecture's own `(7, 7)` default, or the linear layer's input
# shape will not match either checkpoint's `state_dict`.
_PATCH_SIZE = 80


def _get_kernel(height: int, width: int) -> tuple[int, int]:
    """Upstream `src/utility.py::get_kernel`: derives the final `conv_6_dw`
    kernel size from the input resolution so the conv6 receptive field
    always collapses the feature map to exactly 1x1 regardless of input
    size. For 80x80 this is `((80+15)//16, (80+15)//16) == (5, 5)`."""
    return (height + 15) // 16, (width + 15) // 16


_CONV6_KERNEL = _get_kernel(_PATCH_SIZE, _PATCH_SIZE)  # (5, 5) for 80x80 input


class LivenessDetector(ABC):
    """The inference pipeline depends on this, never on a concrete
    liveness-detector class."""

    @property
    @abstractmethod
    def model_version(self) -> str:
        """Version string identifying this detector (analogous to
        `EmbedderInterface.model_version`)."""

    @abstractmethod
    def score(
        self, frame_bgr: Any, bbox_xy: tuple[float, float], bbox_wh: tuple[float, float]
    ) -> float:
        """Liveness score in `[0, 1]` for the face at `(bbox_xy, bbox_wh)`
        in `frame_bgr` -- higher means more likely a live face, lower means
        more likely a spoof (print/replay/mask) attempt."""


class StubLivenessDetector(LivenessDetector):
    """Deterministic placeholder — see module docstring.

    **Design decision**: unlike IN-03's `placeholder_liveness_score` (a
    fixed `1.0` constant), this stub derives a score from a hash of the
    input pixels + bbox, the same "deterministic pseudo-signal" shape as
    `StubEmbedder` (same input -> same output; different inputs -> different,
    effectively uncorrelated outputs). This is STILL not a real liveness
    check -- it carries no anti-spoofing signal whatsoever -- but a
    fixed-`1.0` stub would make it impossible to unit-test the new
    `SPOOF_SUSPECTED` voting path in `ai_inference.pipeline.recognize`
    without immediately switching to the real (heavy, weight-file-dependent)
    detector. A hash-seeded stub lets tests exercise BOTH the "frame looks
    live" and "frame looks spoofed" branches deterministically by picking
    pixel data that hashes above/below the configured threshold, while
    remaining just as clearly a non-real placeholder as `StubEmbedder` is.
    """

    def __init__(self, version: str = "stub-v1") -> None:
        self._version = version

    @property
    def model_version(self) -> str:
        return self._version

    def score(
        self, frame_bgr: Any, bbox_xy: tuple[float, float], bbox_wh: tuple[float, float]
    ) -> float:
        arr = np.asarray(frame_bgr)
        digest = hashlib.sha256(arr.tobytes() + repr((bbox_xy, bbox_wh)).encode()).digest()
        # Top 4 bytes -> uniform float in [0, 1]. Deterministic given the
        # same frame + bbox, uncorrelated with anything about real liveness.
        as_int = int.from_bytes(digest[:4], "big")
        return as_int / 0xFFFFFFFF


class MiniFASNetLivenessDetector(LivenessDetector):
    """Real MiniFASNet ensemble PAD (IN-04).

    **Procedure** (ported from upstream `anti_spoof_predict.py` +
    `generate_patches.py` + `utility.py` + `data_io/transform.py` — see
    `ai_training.liveness.minifasnet_net` module docstring for licensing):

    1. Two models run on the SAME frame, each on its OWN scale-cropped
       `80x80` patch (`ai_training.liveness.patch_crop.crop_patch`):
       - MiniFASNetV2, `scale=2.7`, weights `minifasnet_v2_weights_path`.
       - MiniFASNetV1SE, `scale=4.0`, weights `minifasnet_v1se_weights_path`.
       Both use `conv6_kernel=(5, 5)` (see `_CONV6_KERNEL` above), NOT the
       architecture's own `(7, 7)` default -- required for the 80x80 input.
    2. Each patch -> `(1, 3, 80, 80)` float32 tensor via `ToTensor` semantics
       ONLY (HWC uint8 BGR [0,255] -> CHW float32 BGR [0,1], no mean/std
       normalization, no channel flip -- see `_to_tensor` docstring for why
       BGR is correct here, same reasoning as
       `ai_training.embedding.embedder.preprocess_bgr_crop`).
    3. `softmax(model(tensor), dim=1)` per model (3-class), then the two
       probability vectors are SUMMED elementwise (`probs_a + probs_b`).
    4. **Reinterpreted final score** (deliberate deviation from upstream,
       documented per task brief): upstream takes `argmax` then reports
       `prediction[label] / 2` -- a binary real/fake decision dressed up as
       a "confidence" number, not a smoothly comparable continuous score.
       This project instead needs ONE continuous `[0, 1]` value it can
       threshold independently (`ai_inference.config.Settings.liveness_threshold`,
       not yet calibrated against real attack data -- see that field's
       docstring), so `liveness_score = summed[0][1] / 2.0`: index 1 is
       upstream's "REAL" class, and dividing by 2 accounts for having summed
       two independent softmax distributions (each already sums to 1, so the
       elementwise sum's REAL component sums to at most 2).

    Lazy-loads BOTH models once (first `score()` call) and reuses them for
    this instance's lifetime -- `__init__` touches neither disk nor torch,
    mirroring `AdaFaceEmbedder`.
    """

    # Upstream `anti_spoof_predict.py`'s two-model ensemble: (arch factory,
    # crop scale, weights-path attribute on LivenessSettings).
    _REAL_CLASS_INDEX = 1  # upstream's 3-class label convention: 1 == "REAL"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model_v2: Any = None  # lazy-loaded MiniFASNetV2, scale=2.7
        self._model_v1se: Any = None  # lazy-loaded MiniFASNetV1SE, scale=4.0

    @property
    def model_version(self) -> str:
        """Stable across runs (not a checkpoint hash) -- mirrors
        `AdaFaceEmbedder.model_version`'s stability contract."""
        return "minifasnet-v2-2.7-v1se-4.0-ensemble"

    def _v2_weights_path(self) -> Path:
        configured = self._settings.liveness.minifasnet_v2_weights_path
        if configured:
            return Path(configured)
        return _default_models_dir() / "2.7_80x80_MiniFASNetV2.pth"

    def _v1se_weights_path(self) -> Path:
        configured = self._settings.liveness.minifasnet_v1se_weights_path
        if configured:
            return Path(configured)
        return _default_models_dir() / "4_0_0_80x80_MiniFASNetV1SE.pth"

    def _load_state_dict(self, torch_module: Any, weights_path: Path) -> dict[str, Any]:
        """Strip a `module.` prefix left over from upstream's `DataParallel`
        training, if present -- same pattern as `AdaFace`'s `model.` prefix
        strip in `download_adaface_weights.py`, different literal prefix."""
        raw = torch_module.load(weights_path, map_location="cpu")
        first_key = next(iter(raw))
        if first_key.startswith("module."):
            return {key[len("module."):]: value for key, value in raw.items()}
        return raw

    def _get_models(self) -> tuple[Any, Any]:
        if self._model_v2 is not None and self._model_v1se is not None:
            return self._model_v2, self._model_v1se
        try:
            import torch
        except ImportError as exc:  # pragma: no cover - depends on extras
            raise RuntimeError(
                "MiniFASNetLivenessDetector requires the 'ml' extra (uv sync --extra ml): torch."
            ) from exc

        from ai_training.liveness import minifasnet_net

        v2_path = self._v2_weights_path()
        if not v2_path.is_file():
            raise RuntimeError(
                f"MiniFASNetV2 weights not found at '{v2_path}'. This file ships committed in "
                "the repo (Apache-2.0, ~1.8MB, see root .gitignore's MiniFASNet exception block) "
                "-- if it's missing, restore it from git or set "
                "TRN_LIVENESS__MINIFASNET_V2_WEIGHTS_PATH."
            )
        v1se_path = self._v1se_weights_path()
        if not v1se_path.is_file():
            raise RuntimeError(
                f"MiniFASNetV1SE weights not found at '{v1se_path}'. This file ships committed "
                "in the repo (Apache-2.0, ~1.8MB, see root .gitignore's MiniFASNet exception "
                "block) -- if it's missing, restore it from git or set "
                "TRN_LIVENESS__MINIFASNET_V1SE_WEIGHTS_PATH."
            )

        model_v2 = minifasnet_net.MiniFASNetV2(conv6_kernel=_CONV6_KERNEL)
        model_v2.load_state_dict(self._load_state_dict(torch, v2_path))
        model_v2.eval()

        model_v1se = minifasnet_net.MiniFASNetV1SE(conv6_kernel=_CONV6_KERNEL)
        model_v1se.load_state_dict(self._load_state_dict(torch, v1se_path))
        model_v1se.eval()

        self._model_v2 = model_v2
        self._model_v1se = model_v1se
        return model_v2, model_v1se

    def score(
        self, frame_bgr: Any, bbox_xy: tuple[float, float], bbox_wh: tuple[float, float]
    ) -> float:
        # `_get_models()` must run BEFORE any unguarded `import torch` here,
        # so a bare environment without the 'ml' extra surfaces the
        # actionable RuntimeError, not a raw ModuleNotFoundError.
        model_v2, model_v1se = self._get_models()
        import torch
        import torch.nn.functional as torch_functional

        from ai_training.liveness.patch_crop import crop_patch

        patch_v2 = crop_patch(frame_bgr, bbox_xy, bbox_wh, scale=2.7, out_size=_PATCH_SIZE)
        patch_v1se = crop_patch(frame_bgr, bbox_xy, bbox_wh, scale=4.0, out_size=_PATCH_SIZE)

        tensor_v2 = _to_tensor(patch_v2)
        tensor_v1se = _to_tensor(patch_v1se)

        with torch.no_grad():
            probs_v2 = torch_functional.softmax(model_v2(torch.from_numpy(tensor_v2)), dim=1)
            probs_v1se = torch_functional.softmax(
                model_v1se(torch.from_numpy(tensor_v1se)), dim=1
            )
            summed = probs_v2 + probs_v1se

        return float(summed[0][self._REAL_CLASS_INDEX].item() / 2.0)


def _to_tensor(patch_bgr: np.ndarray) -> np.ndarray:
    """Upstream `data_io/transform.py`'s `ToTensor` semantics ONLY: HWC
    uint8 BGR [0, 255] -> CHW float32 [0, 1], no mean/std normalization, no
    channel flip. The source pipeline decodes frames as BGR (`cv2`), and
    MiniFASNet was trained on BGR crops from that same upstream pipeline --
    identical reasoning to why
    `ai_training.embedding.embedder.preprocess_bgr_crop` does not flip
    channels either."""
    arr = np.asarray(patch_bgr)
    chw = arr.transpose(2, 0, 1).astype(np.float32) / 255.0
    return np.expand_dims(chw, axis=0)


def _default_models_dir() -> Path:
    """`<ai-training project root>/models/`.

    This module lives at `src/ai_training/liveness/detector.py`;
    `parents[3]` from there is the `ai-training/` project root (liveness ->
    ai_training -> src -> ai-training), sibling to `models/` -- same
    resolution pattern as `quality.pose._default_face_landmarker_model_path`
    and `download_adaface_weights.default_weights_path`.
    """
    return Path(__file__).resolve().parents[3] / "models"


def build_liveness_detector(settings: Settings) -> LivenessDetector:
    """Factory selecting the liveness backend from configuration
    (`TRN_LIVENESS__BACKEND`, default `"stub"`) -- mirrors
    `ai_training.embedding.embedder.build_embedder`."""
    if settings.liveness.backend == "minifasnet":
        return MiniFASNetLivenessDetector(settings)
    return StubLivenessDetector()
