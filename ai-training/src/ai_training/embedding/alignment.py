"""Face alignment: crop+warp a detected face to a standard 112x112 frame
(TR-03), following the AdaFace/ArcFace 5-point convention for future-proofing
against the real embedder once AdaFace weights are procured.

The similarity-transform MATH (`estimate_similarity_transform`) is plain
numpy (Umeyama's method) and unit-tested directly. The actual pixel warp
(`align_face`) needs `cv2.warpAffine` and is lazily imported (the `ml`
extra) — not covered by automated tests for the same reason as
`quality.pipeline` (needs a real image + the extra installed).
"""

from __future__ import annotations

from typing import Any

import numpy as np

# Standard 5-point ArcFace/AdaFace reference landmarks for a 112x112 aligned
# crop (left eye, right eye, nose tip, left mouth corner, right mouth
# corner), in that order — the de-facto standard used across the
# ArcFace/InsightFace/AdaFace ecosystem for `112x112` inputs. Public,
# widely-published geometric constants, not a licensed model artifact.
ARC_FACE_112_TEMPLATE = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float64,
)

ALIGNED_FACE_SIZE = (112, 112)


def estimate_similarity_transform(
    landmarks_5pt: np.ndarray, template: np.ndarray = ARC_FACE_112_TEMPLATE
) -> np.ndarray:
    """Umeyama similarity transform (rotation + uniform scale + translation)
    mapping `landmarks_5pt` (detected, pixel space) onto `template`
    (reference, aligned-crop space). Returns a 2x3 affine matrix suitable
    for `cv2.warpAffine`.

    Pure numpy — no `cv2` dependency — so this is unit-testable without the
    `ml` extra (see `tests/test_alignment.py`).
    """
    src = np.asarray(landmarks_5pt, dtype=np.float64)
    dst = np.asarray(template, dtype=np.float64)
    if src.shape != dst.shape:
        raise ValueError(f"landmark count mismatch: src={src.shape} dst={dst.shape}")

    src_mean = src.mean(axis=0)
    dst_mean = dst.mean(axis=0)
    src_centered = src - src_mean
    dst_centered = dst - dst_mean
    n = src.shape[0]

    covariance = (dst_centered.T @ src_centered) / n
    u, singular_values, vt = np.linalg.svd(covariance)
    d = np.sign(np.linalg.det(u @ vt)) or 1.0
    correction = np.diag([1.0, d])
    rotation = u @ correction @ vt

    src_variance = (src_centered**2).sum() / n
    scale_numerator = (singular_values * np.array([1.0, d])).sum()
    scale = float(scale_numerator / src_variance) if src_variance > 0 else 1.0

    translation = dst_mean - scale * (rotation @ src_mean)

    matrix = np.zeros((2, 3), dtype=np.float64)
    matrix[:2, :2] = scale * rotation
    matrix[:, 2] = translation
    return matrix


def align_face(
    image: Any, landmarks_5pt: np.ndarray, output_size: tuple[int, int] = ALIGNED_FACE_SIZE
) -> Any:
    """Warp `image` so the given 5-point landmarks land on the standard
    ArcFace/AdaFace 112x112 template. Requires `cv2` (the `ml` extra)."""
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - depends on extras
        raise RuntimeError(
            "align_face requires the 'ml' extra (uv sync --extra ml): opencv-python-headless."
        ) from exc
    matrix = estimate_similarity_transform(landmarks_5pt)
    return cv2.warpAffine(image, matrix, output_size, borderValue=0)
