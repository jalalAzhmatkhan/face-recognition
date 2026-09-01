"""Cheap per-frame condition-flag heuristics (EC-IN-01, TSD-edge-cases.md
D-1: "Logging funnel per-stage + flag kondisi").

Pure ``numpy`` -- no cv2/torch/mediapipe imports -- so this module (and its
tests, ``tests/test_condition_flags.py``) works on BASE CI with no ``ml``
extra installed. ``numpy`` itself is a small, non-ML base dependency added
specifically for this (see ``pyproject.toml``): computing a mean and a
4-neighbor Laplacian variance over a face-size crop is a handful of
vectorized array ops, not a model, and easily clears the <1ms/frame budget
this task requires (measured in ``tests/test_condition_flags.py``'s
benchmark test) -- the face-region luma conversion happens EXACTLY ONCE per
frame; the eye/mouth patches used for the placeholder masked/sunglasses
heuristic are sliced out of that same array rather than re-cropping and
re-converting from the original BGR frame.

``compute_condition_flags`` returns the exact dict shape
``backend/app/schemas/access_events.py``'s ``AccessEventIngestRequest.
condition_flags: dict[str, bool] | None`` expects -- keys ``dark``,
``blurry``, ``low_res``, ``masked``, ``sunglasses`` (TSD-edge-cases.md
D-1/D-3's canonical set).

**`masked`/`sunglasses` are a PLACEHOLDER heuristic only** (EC-IN-01 task
brief, TSD-edge-cases.md D-3/C-2): cheap intensity/texture checks around the
eye and mouth landmarks -- NOT a trained classifier. TSD-edge-cases.md D-3
explicitly designates the real signal as a dedicated 3-class classifier
(``masked``/``sunglasses``/``none``, EC-IN-03) and calls out landmark-based
heuristics as "secondary/sanity-check signal only... a landmark detector
guesses features under a mask with confidence that does not reliably drop"
(NIST IR 8311). Treat these two flags as low-confidence, log-only signals;
do not use them for any security-relevant gating, and replace them with
EC-IN-03's classifier output as soon as it lands.
"""

from __future__ import annotations

import numpy as np

# --- Thresholds (placeholders pending calibration from this module's own
# logged output -- TSD-edge-cases.md D-1: "final dikalibrasi dari histogram
# ... log D-1"). All are keyword-overridable so calibration can happen via
# `Settings` later without touching this module. ---

# Mean luma (0-255 scale) below which a face ROI is flagged `dark`. Aligned
# with TSD-edge-cases.md D-3/C-6's SCI-enhancement trigger lower bound
# (mean-luma ROI < 50 activates enhancement) so this flag and that future
# trigger agree on what "dark" means for the same input frame.
DARK_LUMA_THRESHOLD = 50.0

# Variance-of-Laplacian (a standard focus/blur measure) below which a face
# ROI is flagged `blurry`. 100.0 is the commonly-cited starting point for
# this measure on a face-scale crop (Pech-Pacheco et al. 2000's "diagonal
# method" ballpark) -- NOT yet calibrated against this deployment's actual
# cameras/lenses/lighting; recalibrate from this flag's own histogram in
# production logs (D-1).
BLUR_VOL_THRESHOLD = 100.0

# Shortest bbox side (px) below which a face is flagged `low_res` -- matches
# TSD-edge-cases.md D-1's literal "bbox < 80px" and REC 10.1 / D-3/C-1's
# matching-stage minimum face size.
LOW_RES_MIN_PX = 80.0

# --- Placeholder masked/sunglasses heuristic thresholds (see module
# docstring -- interim only, replace with EC-IN-03's classifier). ---

# Sunglasses heuristic: a small patch centered on each eye landmark is
# flagged as "probably occluded by a dark, uniform lens" when it is BOTH
# dark (mean luma) AND unusually uniform (low variance) -- bare skin/eye
# regions are neither this dark nor this flat under normal lighting.
SUNGLASSES_MEAN_MAX = 45.0
SUNGLASSES_VOL_MAX = 150.0

# Masked heuristic: a patch spanning the mouth landmarks (padded down
# towards the chin, to cover where a surgical/cloth mask sits) is flagged
# `masked` when its local texture (variance-of-Laplacian) is unusually low
# -- fabric/paper masks are smoother/less textured than visible lips/teeth/
# skin. Deliberately a LOWER threshold than `BLUR_VOL_THRESHOLD` (this is a
# small, naturally low-texture patch even unmasked -- lips are smoother than
# the whole face) rather than reusing the same cutoff.
MASKED_MOUTH_VOL_MAX = 40.0

_EYE_PATCH_HALF_PX = 6.0
_MOUTH_PATCH_HALF_X_PX = 14.0
_MOUTH_PATCH_UP_PX = 4.0
_MOUTH_PATCH_DOWN_PX = 18.0

# BT.601 luma weights (match OpenCV's own BGR->gray weights) as a single
# vector so the whole 3-channel-weighted-sum collapses to one `np.dot`
# instead of 3 separate channel slices + multiplies + adds.
_LUMA_WEIGHTS_BGR = np.array([0.114, 0.587, 0.299], dtype=np.float32)


def _to_luma(patch_bgr: np.ndarray) -> np.ndarray:
    """ITU-R BT.601 luma, computed directly on the BGR array -- avoids an
    extra `cv2.cvtColor` dependency for a computation this module keeps
    deliberately cv2-free. `patch_bgr` may be any dtype (typically
    `uint8`); returned array is always `float32`."""
    return patch_bgr.astype(np.float32, copy=False) @ _LUMA_WEIGHTS_BGR


def _variance_of_laplacian(luma: np.ndarray) -> float:
    """Vectorized 4-neighbor discrete Laplacian variance -- pure numpy
    slicing, no `cv2.Laplacian` needed. Interior pixels only (drops the
    1px border), which is immaterial for a relative focus measure on a
    face-size crop. Returns 0.0 for a patch too small to have an interior
    (nothing meaningful to measure, treated as "not confidently blurry")."""
    if luma.shape[0] < 3 or luma.shape[1] < 3:
        return 0.0
    center = luma[1:-1, 1:-1]
    up = luma[:-2, 1:-1]
    down = luma[2:, 1:-1]
    left = luma[1:-1, :-2]
    right = luma[1:-1, 2:]
    laplacian = 4.0 * center - up - down - left - right
    return float(np.var(laplacian))


def _clamp_box(
    frame_shape: tuple[int, int], x0: float, y0: float, x1: float, y1: float
) -> tuple[int, int, int, int] | None:
    """Integer-pixel box, clamped to `frame_shape` (`(height, width)`).
    Returns `None` if the (clamped) box is empty -- e.g. a landmark that
    lands exactly on the frame edge, or a degenerate bbox."""
    h, w = frame_shape
    x0c = max(0, min(int(round(x0)), w))
    x1c = max(0, min(int(round(x1)), w))
    y0c = max(0, min(int(round(y0)), h))
    y1c = max(0, min(int(round(y1)), h))
    if x1c <= x0c or y1c <= y0c:
        return None
    return x0c, y0c, x1c, y1c


def _sub_patch(
    luma: np.ndarray, origin_xy: tuple[int, int], x0: float, y0: float, x1: float, y1: float
) -> np.ndarray | None:
    """Slices a sub-region out of an ALREADY-COMPUTED luma array (avoids
    re-cropping + re-converting from the raw BGR frame for every eye/mouth
    patch -- see module docstring). `origin_xy` is where `luma`'s (0, 0)
    sits in the same absolute pixel coordinates as `x0..y1`; the requested
    box is intersected with `luma`'s own bounds (a landmark can legitimately
    sit right at the edge of the detected face bbox)."""
    ox, oy = origin_xy
    box = _clamp_box(luma.shape, x0 - ox, y0 - oy, x1 - ox, y1 - oy)
    if box is None:
        return None
    rx0, ry0, rx1, ry1 = box
    return luma[ry0:ry1, rx0:rx1]


def compute_condition_flags(
    frame_bgr: np.ndarray,
    *,
    bbox_xy: tuple[float, float],
    bbox_wh: tuple[float, float],
    left_eye: tuple[float, float],
    right_eye: tuple[float, float],
    left_mouth: tuple[float, float],
    right_mouth: tuple[float, float],
    dark_luma_threshold: float = DARK_LUMA_THRESHOLD,
    blur_vol_threshold: float = BLUR_VOL_THRESHOLD,
    low_res_min_px: float = LOW_RES_MIN_PX,
    sunglasses_mean_max: float = SUNGLASSES_MEAN_MAX,
    sunglasses_vol_max: float = SUNGLASSES_VOL_MAX,
    masked_mouth_vol_max: float = MASKED_MOUTH_VOL_MAX,
) -> dict[str, bool]:
    """One frame's `condition_flags` (TSD-edge-cases.md D-1): `dark`,
    `blurry`, `low_res` are cheap, reasonably-trustworthy signals; `masked`/
    `sunglasses` are the placeholder heuristic described in the module
    docstring. All inputs are plain pixel-coordinate tuples (as returned by
    `ai_training.quality.pose.FaceDetection`) rather than that dataclass
    itself, so this module has zero dependency on the `ml` extra.

    Never raises on a degenerate/edge-of-frame bbox or landmark -- an
    unmeasurable flag simply defaults to `False` (see `_clamp_box`), since
    a condition flag that can't be computed should not be reported as
    positive.

    Eye/mouth landmarks are assumed to fall INSIDE `bbox_xy`/`bbox_wh`
    (true for every real detection -- `ai_training.quality.pose.
    FaceDetection`'s bbox is the landmark bounding box itself); the eye and
    mouth patches are sliced out of the face crop's ALREADY-COMPUTED luma
    array rather than re-cropped/re-converted from `frame_bgr` (the single
    most expensive part of this function), which is what keeps this
    comfortably under the <1ms/frame budget.
    """
    x0, y0 = bbox_xy
    w, h = bbox_wh
    low_res = bool(min(w, h) < low_res_min_px)

    box = _clamp_box(frame_bgr.shape[:2], x0, y0, x0 + w, y0 + h)
    if box is None:
        # No usable pixels at all for this bbox -- only `low_res` (computed
        # from bbox dimensions alone) can be trusted here.
        return {
            "dark": False,
            "blurry": False,
            "low_res": low_res,
            "masked": False,
            "sunglasses": False,
        }
    fx0, fy0, fx1, fy1 = box
    face_luma = _to_luma(frame_bgr[fy0:fy1, fx0:fx1])
    dark = bool(np.mean(face_luma) < dark_luma_threshold)
    blurry = bool(_variance_of_laplacian(face_luma) < blur_vol_threshold)

    eye_luma_patches = []
    for ex, ey in (left_eye, right_eye):
        patch = _sub_patch(
            face_luma,
            (fx0, fy0),
            ex - _EYE_PATCH_HALF_PX,
            ey - _EYE_PATCH_HALF_PX,
            ex + _EYE_PATCH_HALF_PX,
            ey + _EYE_PATCH_HALF_PX,
        )
        if patch is not None and patch.size:
            eye_luma_patches.append(patch.ravel())
    if eye_luma_patches:
        eye_luma = np.concatenate(eye_luma_patches)
        sunglasses = bool(
            np.mean(eye_luma) < sunglasses_mean_max and np.var(eye_luma) < sunglasses_vol_max
        )
    else:
        sunglasses = False

    mouth_cx = (left_mouth[0] + right_mouth[0]) / 2.0
    mouth_cy = (left_mouth[1] + right_mouth[1]) / 2.0
    mouth_patch = _sub_patch(
        face_luma,
        (fx0, fy0),
        mouth_cx - _MOUTH_PATCH_HALF_X_PX,
        mouth_cy - _MOUTH_PATCH_UP_PX,
        mouth_cx + _MOUTH_PATCH_HALF_X_PX,
        mouth_cy + _MOUTH_PATCH_DOWN_PX,
    )
    if mouth_patch is not None and mouth_patch.size:
        masked = bool(_variance_of_laplacian(mouth_patch) < masked_mouth_vol_max)
    else:
        masked = False

    return {
        "dark": dark,
        "blurry": blurry,
        "low_res": low_res,
        "masked": masked,
        "sunglasses": sunglasses,
    }


def merge_condition_flags(
    aggregate: dict[str, bool], frame_flags: dict[str, bool]
) -> dict[str, bool]:
    """OR-merge one frame's flags into a request-level aggregate.

    `access_events.condition_flags` is ONE `dict[str, bool]` per decision,
    not a list per frame (`backend/app/schemas/access_events.py`) -- so a
    multi-frame `/recognize` call's per-frame flags are folded with logical
    OR: if any submitted frame showed a condition (dark/blurry/low_res/
    masked/sunglasses), the decision-level event reports it, matching this
    module's "don't let good frames hide a bad one" spirit already used
    elsewhere in this pipeline (`decide_from_scores`'s `SPOOF_SUSPECTED`
    priority, `run_recognition_timed`'s MIN liveness score)."""
    return {key: aggregate.get(key, False) or frame_flags.get(key, False) for key in frame_flags}
