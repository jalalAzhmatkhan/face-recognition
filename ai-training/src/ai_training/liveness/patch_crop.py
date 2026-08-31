"""Scale-crop preprocessing for MiniFASNet (IN-04).

Ports `CropImage.crop`/`_get_new_box` from upstream
`minivision-ai/Silent-Face-Anti-Spoofing`'s `src/generate_patches.py`
(Apache-2.0 — see `ai_training.liveness.minifasnet_net` module docstring for
the full provenance note). Each of the two MiniFASNet variants used here
looks at a DIFFERENT crop of the same frame: a box `scale`-times larger than
the detected face bbox, centered on the bbox center, clamped to the frame
bounds, then resized to `80x80`.

Split into two functions so the box-geometry math (`get_new_box`) stays
unit-testable with plain numpy/tuples -- no cv2 needed -- while
`crop_patch`, which does need `cv2.resize`, is the only place the `ml`
extra is required.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def get_new_box(
    src_w: float, src_h: float, x: float, y: float, box_w: float, box_h: float, scale: float
) -> tuple[int, int, int, int]:
    """Compute the scaled-and-clamped crop box `(left, top, right, bottom)`
    (inclusive-ish integer pixel bounds, matching upstream's own rounding)
    for a bbox `(x, y, box_w, box_h)` scaled by `scale` around its center,
    within a `src_w x src_h` frame. Pure arithmetic, no image data touched.
    """
    scale = min((src_h - 1) / box_h, min((src_w - 1) / box_w, scale))
    new_width = box_w * scale
    new_height = box_h * scale
    center_x, center_y = box_w / 2 + x, box_h / 2 + y
    left_top_x = center_x - new_width / 2
    left_top_y = center_y - new_height / 2
    right_bottom_x = center_x + new_width / 2
    right_bottom_y = center_y + new_height / 2

    if left_top_x < 0:
        right_bottom_x -= left_top_x
        left_top_x = 0
    if left_top_y < 0:
        right_bottom_y -= left_top_y
        left_top_y = 0
    if right_bottom_x > src_w - 1:
        left_top_x -= right_bottom_x - src_w + 1
        right_bottom_x = src_w - 1
    if right_bottom_y > src_h - 1:
        left_top_y -= right_bottom_y - src_h + 1
        right_bottom_y = src_h - 1

    return int(left_top_x), int(left_top_y), int(right_bottom_x), int(right_bottom_y)


def crop_patch(
    frame_bgr: Any,
    bbox_xy: tuple[float, float],
    bbox_wh: tuple[float, float],
    scale: float,
    out_size: int = 80,
) -> np.ndarray:
    """Crop the `scale`-expanded region around `(bbox_xy, bbox_wh)` out of
    `frame_bgr` and resize it to `(out_size, out_size)`. Requires the `ml`
    extra (`cv2.resize`) -- `get_new_box` above is the cv2-free part of this
    same logic, kept separate so it stays testable without it."""
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - depends on extras
        raise RuntimeError(
            "crop_patch requires the 'ml' extra (uv sync --extra ml): opencv-python-headless."
        ) from exc

    frame = np.asarray(frame_bgr)
    src_h, src_w = frame.shape[:2]
    x, y = bbox_xy
    box_w, box_h = bbox_wh
    left, top, right, bottom = get_new_box(src_w, src_h, x, y, box_w, box_h, scale)
    region = frame[top : bottom + 1, left : right + 1]
    return cv2.resize(region, (out_size, out_size))
