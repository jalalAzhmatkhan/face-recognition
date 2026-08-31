"""Pure-numpy tests for `ai_training.liveness.patch_crop.get_new_box` (IN-04)
-- no cv2 needed, must pass on base CI (no `ml` extra). `crop_patch` itself
(which does need `cv2.resize`) is exercised only when the `ml` extra is
installed, see `test_crop_patch_requires_ml_extra` below."""

import numpy as np
import pytest

from ai_training.liveness.patch_crop import crop_patch, get_new_box


def test_get_new_box_centered_bbox_scales_around_center() -> None:
    # 100x100 frame, a 20x20 bbox centered at (40, 40)..(60, 60), scale=2.0
    # -> new box should be 40x40 centered on the same center (60, 60).
    left, top, right, bottom = get_new_box(100, 100, 40, 40, 20, 20, scale=2.0)
    assert (right - left) == pytest.approx(40, abs=1)
    assert (bottom - top) == pytest.approx(40, abs=1)
    center_x = (left + right) / 2
    center_y = (top + bottom) / 2
    assert center_x == pytest.approx(50, abs=1)
    assert center_y == pytest.approx(50, abs=1)


def test_get_new_box_clamps_near_left_top_edge() -> None:
    # bbox near the top-left corner: scaling up must not go negative.
    left, top, right, bottom = get_new_box(100, 100, 0, 0, 10, 10, scale=4.0)
    assert left >= 0
    assert top >= 0
    assert right <= 99
    assert bottom <= 99


def test_get_new_box_clamps_near_right_bottom_edge() -> None:
    # bbox near the bottom-right corner: scaling up must not exceed bounds.
    left, top, right, bottom = get_new_box(100, 100, 85, 85, 10, 10, scale=4.0)
    assert left >= 0
    assert top >= 0
    assert right <= 99
    assert bottom <= 99


def test_get_new_box_large_scale_is_clamped_to_frame_size() -> None:
    # An extreme scale on a bbox that already nearly fills the frame must
    # clamp to (approximately) the whole frame, not overflow.
    left, top, right, bottom = get_new_box(50, 50, 5, 5, 40, 40, scale=10.0)
    assert left >= 0
    assert top >= 0
    assert right <= 49
    assert bottom <= 49


def test_get_new_box_returns_ints() -> None:
    result = get_new_box(100, 100, 40, 40, 20, 20, scale=2.7)
    assert all(isinstance(v, int) for v in result)


def test_crop_patch_requires_ml_extra_or_produces_expected_shape() -> None:
    # Whether or not cv2 is installed, this call must either succeed with
    # the expected output shape (ml extra present) or raise the actionable
    # RuntimeError (ml extra absent) -- never a raw ImportError.
    frame = np.zeros((200, 200, 3), dtype=np.uint8)
    try:
        result = crop_patch(frame, bbox_xy=(50, 50), bbox_wh=(60, 60), scale=2.7, out_size=80)
    except RuntimeError as exc:
        assert "ml' extra" in str(exc) or "ml extra" in str(exc)
    else:
        assert result.shape[:2] == (80, 80)
