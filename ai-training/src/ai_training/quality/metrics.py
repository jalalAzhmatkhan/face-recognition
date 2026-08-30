"""Real, dependency-light quality metrics for enrollment frames (TR-02).

Deliberately implemented with plain `numpy` only (no `cv2`) so these are
unit-testable on synthetic arrays without the `ml` extra installed — see
`ai-training/tests/test_quality_metrics.py`. Frames from the real pipeline
(`ai_training.quality.pipeline`) are OpenCV `ndarray`s in BGR order; these
functions do not care about channel order beyond the (approximate)
luminosity weighting in `_to_grayscale`, which is symmetric enough for QC
purposes (we need "how sharp/bright is this", not colorimetric accuracy).
"""

from __future__ import annotations

import numpy as np

# Discrete Laplacian kernel (4-neighbour), the standard "variance of
# Laplacian" blur-detection kernel (Pech-Pacheco et al., 2000).
_LAPLACIAN_KERNEL = np.array([[0.0, 1.0, 0.0], [1.0, -4.0, 1.0], [0.0, 1.0, 0.0]])

# BGR (OpenCV convention) luminosity weights; also correct if the caller
# happens to pass RGB since the weights differ by <0.02 either way and QC
# thresholds have far more slack than that.
_LUMA_WEIGHTS = np.array([0.114, 0.587, 0.299])


def _to_grayscale(image: np.ndarray) -> np.ndarray:
    arr = np.asarray(image, dtype=np.float64)
    if arr.ndim == 2:
        return arr
    if arr.ndim == 3 and arr.shape[2] >= 3:
        return arr[:, :, :3] @ _LUMA_WEIGHTS
    raise ValueError(f"expected a 2D grayscale or 3-channel image, got shape {arr.shape}")


def _convolve2d_valid(gray: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    """Minimal "valid"-mode 2D convolution, kernel-size-agnostic but only
    ever called here with the small fixed 3x3 Laplacian kernel above, so a
    plain Python double loop over kernel taps (not image pixels) is cheap.
    """
    kh, kw = kernel.shape
    h, w = gray.shape
    if h < kh or w < kw:
        raise ValueError(f"image too small ({h}x{w}) for a {kh}x{kw} kernel")
    out = np.zeros((h - kh + 1, w - kw + 1), dtype=np.float64)
    for i in range(kh):
        for j in range(kw):
            weight = kernel[i, j]
            if weight == 0.0:
                continue
            out += weight * gray[i : i + out.shape[0], j : j + out.shape[1]]
    return out


def blur_score(image: np.ndarray) -> float:
    """Variance of the Laplacian — higher means sharper. A near-uniform or
    smoothly-varying image (blurred/out-of-focus) has low high-frequency
    energy and therefore low variance after this edge-detecting filter.
    """
    gray = _to_grayscale(image)
    laplacian = _convolve2d_valid(gray, _LAPLACIAN_KERNEL)
    return float(laplacian.var())


def brightness_score(image: np.ndarray) -> float:
    """Mean pixel intensity (0-255 scale for uint8 input) — a cheap proxy
    for over/under-exposure."""
    gray = _to_grayscale(image)
    return float(gray.mean())


def face_size_ratio(face_bbox_wh: tuple[float, float], frame_wh: tuple[float, float]) -> float:
    """Fraction of the frame's area occupied by the detected face bbox —
    proxy for "is the subject close enough to the camera"."""
    face_w, face_h = face_bbox_wh
    frame_w, frame_h = frame_wh
    if frame_w <= 0 or frame_h <= 0:
        return 0.0
    return float((face_w * face_h) / (frame_w * frame_h))
