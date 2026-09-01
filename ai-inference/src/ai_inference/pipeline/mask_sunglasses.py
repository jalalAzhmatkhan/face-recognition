"""EC-IN-03 (TSD-edge-cases.md C-2/OQ-4): ONNX Runtime serving wrapper for
the own-model masked/sunglasses classifier trained in
`ai_training.classifiers.mask_sunglasses`.

This is the module that replaces EC-IN-01's placeholder landmark-intensity
heuristic (`ai_inference.pipeline.condition_flags`'s `masked`/`sunglasses`
flags) with the real classifier's output, per the task brief. It lives
under the `ml` extra (needs `onnxruntime`, already a base `ml`-extra
dependency -- see `pyproject.toml`) and is imported LAZILY, exactly like
every other heavy-extra module in this pipeline (`ai_training.embedding.*`,
`ai_inference.models.loader`) -- so importing this module itself never
crashes a base install; only *calling* `load_classifier` needs the extra.

**Fail-safe by construction**: `load_classifier` NEVER raises. A missing
`onnxruntime` install, a missing/corrupt model file, or any other load-time
error is caught, logged as a warning, and reported as `None` -- callers
(`ai_inference.pipeline.recognize`, `ai_inference.pipeline.condition_flags`)
treat `None` as "classifier unavailable, fall back to the EC-IN-01
heuristic", never as a reason to fail the request. This mirrors this
project's existing "stub loader" convention (`ai_inference.models.loader`)
for exactly the same reason: a missing ML artifact must degrade gracefully,
not take down `/recognize`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from ai_inference.config import get_settings

logger = logging.getLogger(__name__)

# Must match `ai_training.classifiers.mask_sunglasses.LABEL_NAMES` order --
# duplicated here (rather than imported) so this module's *class* stays
# import-safe without pulling in ai-training's own `ml` extra: `Classifier
# .classify` only needs `onnxruntime` + `numpy`, not `torch`. The ONNX
# graph's `logits` output order is baked in at export time either way, so
# this constant is the single source of truth this module actually depends
# on.
LABEL_NAMES: tuple[str, str] = ("masked", "sunglasses")

_ONNX_INPUT_NAME = "crop"


@dataclass
class MaskSunglassesClassifier:
    """Loaded ONNX Runtime session + the pre/post-processing needed to go
    from a BGR face crop to `(masked, sunglasses)` booleans.

    `session` is untyped (`onnxruntime.InferenceSession`) so this
    dataclass's own import doesn't require `onnxruntime` -- only
    `load_classifier`/`classify` (which run the actual lazy import) do.
    """

    session: object
    img_size: int
    masked_threshold: float
    sunglasses_threshold: float

    def classify(self, crop_bgr: np.ndarray) -> tuple[bool, bool] | None:
        """Runs one face crop through the model. Returns `None` (never
        raises) on any preprocessing/inference error -- callers fall back
        to the EC-IN-01 heuristic exactly as they would for a missing
        session, so a single bad frame can never take down `/recognize`.
        """
        try:
            input_tensor = _preprocess(crop_bgr, self.img_size)
            (logits,) = self.session.run(None, {_ONNX_INPUT_NAME: input_tensor})
            probs = _sigmoid(logits[0])
            masked = bool(probs[0] >= self.masked_threshold)
            sunglasses = bool(probs[1] >= self.sunglasses_threshold)
            return masked, sunglasses
        except Exception:
            logger.warning(
                "mask_sunglasses classifier inference failed; caller should fall back "
                "to the EC-IN-01 heuristic for this frame",
                exc_info=True,
            )
            return None


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x.astype(np.float64, copy=False)))


def _preprocess(crop_bgr: np.ndarray, img_size: int) -> np.ndarray:
    """BGR uint8 HxWx3 crop -> the `1x3xHxW` float32 NCHW tensor the
    exported ONNX graph expects (see `ai_training.classifiers.
    mask_sunglasses.build_model`'s `Conv2d(3, ...)` first layer).

    Resize uses `cv2` (lazy import -- already a transitive `ml`-extra
    dependency via `ai-training[ml]`'s `opencv-python-headless`, per
    `pyproject.toml`'s `ml` extra comment; no NEW dependency needed here).
    Pixel values are scaled to `[0, 1]` and channel order flipped BGR->RGB
    to match `ai_training.classifiers.mask_sunglasses.build_synthetic_dataset`'s
    `torch.rand(...)` convention of plain `[0, 1]`-scaled RGB-order tensors
    -- keep training and serving preprocessing in lockstep if either
    changes.
    """
    import cv2

    if crop_bgr.size == 0:
        raise ValueError("empty crop")
    resized = cv2.resize(crop_bgr, (img_size, img_size), interpolation=cv2.INTER_LINEAR)
    rgb = resized[:, :, ::-1]
    chw = np.transpose(rgb, (2, 0, 1)).astype(np.float32) / 255.0
    return np.ascontiguousarray(chw[np.newaxis, ...])


def load_classifier(
    model_path: str,
    *,
    img_size: int | None = None,
    masked_threshold: float | None = None,
    sunglasses_threshold: float | None = None,
) -> MaskSunglassesClassifier | None:
    """Loads the ONNX model at `model_path` into a single-thread ONNX
    Runtime session (`intra_op_num_threads=1`, TSD-edge-cases.md C-2's
    "ONNX Runtime single-thread" -- single-thread is deliberate here, not
    an oversight: this runs per-frame on the request hot path alongside
    detection/liveness/embedding, and thread-pool contention across those
    stages is a bigger risk than single-thread op latency for a model this
    small).

    Returns `None` -- logging a clear warning, NEVER raising -- when:
    - `onnxruntime` is not installed (base install, no `ml` extra), or
    - `model_path` is empty/missing/unreadable, or
    - the file exists but fails to load as a valid ONNX graph.

    See module docstring: this fail-safe contract is exactly what lets
    `ai_inference.pipeline.condition_flags`/`recognize` treat "classifier
    unavailable" as a normal, expected state (fall back to the EC-IN-01
    heuristic) rather than a crash.
    """
    settings = get_settings()
    img_size = img_size if img_size is not None else settings.mask_sunglasses_img_size
    masked_threshold = (
        masked_threshold
        if masked_threshold is not None
        else settings.mask_sunglasses_masked_threshold
    )
    sunglasses_threshold = (
        sunglasses_threshold
        if sunglasses_threshold is not None
        else settings.mask_sunglasses_sunglasses_threshold
    )

    if not model_path:
        logger.warning(
            "mask_sunglasses classifier model path not configured "
            "(INF_MASK_SUNGLASSES_MODEL_PATH); falling back to the EC-IN-01 heuristic"
        )
        return None

    try:
        import onnxruntime as ort
    except ImportError:
        logger.warning(
            "onnxruntime not installed (base install without the `ml` extra); "
            "falling back to the EC-IN-01 heuristic for masked/sunglasses"
        )
        return None

    try:
        session_options = ort.SessionOptions()
        session_options.intra_op_num_threads = 1
        session = ort.InferenceSession(
            model_path, sess_options=session_options, providers=["CPUExecutionProvider"]
        )
    except Exception:
        logger.warning(
            "failed to load mask_sunglasses ONNX model from %s; falling back to the "
            "EC-IN-01 heuristic",
            model_path,
            exc_info=True,
        )
        return None

    return MaskSunglassesClassifier(
        session=session,
        img_size=img_size,
        masked_threshold=masked_threshold,
        sunglasses_threshold=sunglasses_threshold,
    )


@lru_cache
def get_classifier() -> MaskSunglassesClassifier | None:
    """Process-wide cached singleton, keyed by nothing (this process has
    exactly one configured model path/settings instance) -- avoids
    re-loading the ONNX session on every `/recognize` frame. Mirrors
    `ai_inference.config.get_settings`'s own `lru_cache` singleton
    convention. Call `get_classifier.cache_clear()` in tests that need a
    fresh load (e.g. after monkeypatching settings).
    """
    settings = get_settings()
    return load_classifier(settings.mask_sunglasses_model_path)
