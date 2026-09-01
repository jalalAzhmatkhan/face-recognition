"""Unit tests for the EC-IN-01 per-frame condition-flag heuristics
(TSD-edge-cases.md D-1): `ai_inference.pipeline.condition_flags`. Pure
numpy, no cv2/torch/mediapipe -- must pass on base CI (no `ml` extra), per
this module's own docstring.

Synthetic BGR frames are built directly with numpy so these tests don't
need a real camera frame or the `ml` extra's decode path (`cv2.imdecode`,
tested separately/live per `ai_inference.pipeline.recognize`'s module
docstring convention).
"""

from __future__ import annotations

import numpy as np
import pytest

from ai_inference.pipeline.condition_flags import (
    BLUR_VOL_THRESHOLD,
    DARK_LUMA_THRESHOLD,
    LOW_RES_MIN_PX,
    compute_condition_flags,
    merge_condition_flags,
)

# A generous bbox comfortably >= LOW_RES_MIN_PX on both sides, centered in
# a 200x200 frame, with landmark positions placed at plausible relative
# offsets inside it (eyes upper third, mouth lower third) -- exact pixel
# values don't matter, only that eye/mouth patches land inside the frame.
_FRAME_SIZE = 200
_BBOX_XY = (40.0, 30.0)
_BBOX_WH = (120.0, 140.0)
_LEFT_EYE = (70.0, 70.0)
_RIGHT_EYE = (130.0, 70.0)
_LEFT_MOUTH = (80.0, 140.0)
_RIGHT_MOUTH = (120.0, 140.0)


def _base_kwargs(frame_bgr: np.ndarray) -> dict:
    return dict(
        frame_bgr=frame_bgr,
        bbox_xy=_BBOX_XY,
        bbox_wh=_BBOX_WH,
        left_eye=_LEFT_EYE,
        right_eye=_RIGHT_EYE,
        left_mouth=_LEFT_MOUTH,
        right_mouth=_RIGHT_MOUTH,
    )


def _solid_frame(gray_value: int) -> np.ndarray:
    """A flat BGR frame at one uniform intensity -- zero texture, exact
    known mean luma (B=G=R so BT.601 luma == gray_value exactly)."""
    frame = np.full((_FRAME_SIZE, _FRAME_SIZE, 3), gray_value, dtype=np.uint8)
    return frame


def _textured_frame(base_value: int, rng_seed: int = 0) -> np.ndarray:
    """A frame with real per-pixel variation (checkerboard-ish high-freq
    noise) so its variance-of-Laplacian is large -- the "sharp"/"in focus"
    counterpart to `_solid_frame`'s zero-texture flatness."""
    rng = np.random.default_rng(rng_seed)
    noise = rng.integers(-60, 60, size=(_FRAME_SIZE, _FRAME_SIZE), endpoint=True)
    channel = np.clip(base_value + noise, 0, 255).astype(np.uint8)
    return np.stack([channel, channel, channel], axis=-1)


# --- dark ---------------------------------------------------------------


def test_dark_flag_true_for_low_luma_frame() -> None:
    frame = _solid_frame(gray_value=10)  # well below DARK_LUMA_THRESHOLD
    flags = compute_condition_flags(**_base_kwargs(frame))
    assert flags["dark"] is True


def test_dark_flag_false_for_bright_frame() -> None:
    frame = _solid_frame(gray_value=200)  # well above DARK_LUMA_THRESHOLD
    flags = compute_condition_flags(**_base_kwargs(frame))
    assert flags["dark"] is False


def test_dark_threshold_boundary_is_strict_less_than() -> None:
    # Exactly at threshold -> NOT dark (strict `<`, not `<=`).
    frame = _solid_frame(gray_value=int(DARK_LUMA_THRESHOLD))
    flags = compute_condition_flags(**_base_kwargs(frame))
    assert flags["dark"] is False


# --- blurry ---------------------------------------------------------------


def test_blurry_flag_true_for_flat_textureless_frame() -> None:
    # A perfectly flat frame has variance-of-Laplacian == 0.0.
    frame = _solid_frame(gray_value=128)
    flags = compute_condition_flags(**_base_kwargs(frame))
    assert flags["blurry"] is True


def test_blurry_flag_false_for_sharp_high_texture_frame() -> None:
    frame = _textured_frame(base_value=128)
    flags = compute_condition_flags(**_base_kwargs(frame))
    assert flags["blurry"] is False


def test_blur_vol_threshold_is_documented_positive_value() -> None:
    # Sanity-pin the calibration-pending constant so an accidental edit
    # doesn't silently change behavior without a test failing.
    assert BLUR_VOL_THRESHOLD == 100.0


# --- low_res --------------------------------------------------------------


def test_low_res_true_for_small_bbox() -> None:
    frame = _solid_frame(gray_value=128)
    flags = compute_condition_flags(
        frame_bgr=frame,
        bbox_xy=(50.0, 50.0),
        bbox_wh=(60.0, 70.0),  # shortest side 60 < LOW_RES_MIN_PX (80)
        left_eye=_LEFT_EYE,
        right_eye=_RIGHT_EYE,
        left_mouth=_LEFT_MOUTH,
        right_mouth=_RIGHT_MOUTH,
    )
    assert flags["low_res"] is True


def test_low_res_false_for_large_bbox() -> None:
    frame = _solid_frame(gray_value=128)
    flags = compute_condition_flags(**_base_kwargs(frame))  # 120x140, both >= 80
    assert flags["low_res"] is False


def test_low_res_uses_shortest_side() -> None:
    frame = _solid_frame(gray_value=128)
    flags = compute_condition_flags(
        frame_bgr=frame,
        bbox_xy=(10.0, 10.0),
        bbox_wh=(150.0, 79.0),  # width plenty, height just under the floor
        left_eye=_LEFT_EYE,
        right_eye=_RIGHT_EYE,
        left_mouth=_LEFT_MOUTH,
        right_mouth=_RIGHT_MOUTH,
    )
    assert flags["low_res"] is True


def test_low_res_min_px_matches_tsd_spec() -> None:
    assert LOW_RES_MIN_PX == 80.0


# --- masked / sunglasses placeholder heuristic -----------------------------


def test_sunglasses_flag_true_for_dark_uniform_eye_patches() -> None:
    # Whole frame bright/textured EXCEPT small dark, flat patches exactly
    # where the eye landmarks are -- simulates a dark, uniform lens
    # occluding just the eyes.
    frame = _textured_frame(base_value=180)
    for ex, ey in (_LEFT_EYE, _RIGHT_EYE):
        x0, y0 = int(ex) - 6, int(ey) - 6
        frame[y0 : y0 + 12, x0 : x0 + 12] = 5
    flags = compute_condition_flags(**_base_kwargs(frame))
    assert flags["sunglasses"] is True


def test_sunglasses_flag_false_for_normal_bright_eye_region() -> None:
    frame = _textured_frame(base_value=180)
    flags = compute_condition_flags(**_base_kwargs(frame))
    assert flags["sunglasses"] is False


def test_masked_flag_true_for_flat_mouth_patch() -> None:
    # Whole frame textured EXCEPT a flat, low-texture patch spanning the
    # mouth landmarks -- simulates a smooth fabric/paper mask surface.
    frame = _textured_frame(base_value=150)
    mouth_cx = int((_LEFT_MOUTH[0] + _RIGHT_MOUTH[0]) / 2)
    mouth_cy = int((_LEFT_MOUTH[1] + _RIGHT_MOUTH[1]) / 2)
    frame[mouth_cy - 4 : mouth_cy + 18, mouth_cx - 14 : mouth_cx + 14] = 150
    flags = compute_condition_flags(**_base_kwargs(frame))
    assert flags["masked"] is True


def test_masked_flag_false_for_textured_mouth_region() -> None:
    frame = _textured_frame(base_value=150)
    flags = compute_condition_flags(**_base_kwargs(frame))
    assert flags["masked"] is False


# --- EC-IN-03: classifier override + fallback -------------------------------
#
# `classifier` is injected as a plain callable here -- these tests never
# import `ai_inference.pipeline.mask_sunglasses` or touch onnxruntime, so
# they run on base CI (no `ml` extra) exactly like the rest of this file,
# per this module's own "zero ml-extra dependency" docstring guarantee.


def test_classifier_result_overrides_heuristic_when_it_succeeds() -> None:
    # Heuristic alone would say both False (bright, textured frame) --
    # classifier's (True, True) must win.
    frame = _textured_frame(base_value=180)
    flags = compute_condition_flags(
        **_base_kwargs(frame), classifier=lambda crop: (True, True)
    )
    assert flags["masked"] is True
    assert flags["sunglasses"] is True


def test_classifier_returning_none_falls_back_to_heuristic() -> None:
    # Same "dark uniform eye patch" setup as the pure-heuristic sunglasses
    # test above; classifier abstaining (`None`) must not suppress it.
    frame = _textured_frame(base_value=180)
    for ex, ey in (_LEFT_EYE, _RIGHT_EYE):
        x0, y0 = int(ex) - 6, int(ey) - 6
        frame[y0 : y0 + 12, x0 : x0 + 12] = 5
    flags = compute_condition_flags(**_base_kwargs(frame), classifier=lambda crop: None)
    assert flags["sunglasses"] is True


def test_classifier_raising_falls_back_to_heuristic_without_crashing() -> None:
    def _broken_classifier(crop: np.ndarray) -> tuple[bool, bool]:
        raise RuntimeError("simulated inference failure")

    frame = _textured_frame(base_value=150)
    mouth_cx = int((_LEFT_MOUTH[0] + _RIGHT_MOUTH[0]) / 2)
    mouth_cy = int((_LEFT_MOUTH[1] + _RIGHT_MOUTH[1]) / 2)
    frame[mouth_cy - 4 : mouth_cy + 18, mouth_cx - 14 : mouth_cx + 14] = 150

    flags = compute_condition_flags(**_base_kwargs(frame), classifier=_broken_classifier)

    assert flags["masked"] is True  # heuristic result, not a crash


def test_classifier_none_uses_heuristic_unchanged() -> None:
    # Default (no classifier passed at all) must be byte-for-byte the same
    # as passing `classifier=None` explicitly -- EC-IN-01 behavior when no
    # EC-IN-03 model is configured.
    frame = _textured_frame(base_value=180)
    without = compute_condition_flags(**_base_kwargs(frame))
    with_none = compute_condition_flags(**_base_kwargs(frame), classifier=None)
    assert without == with_none


def test_classifier_receives_the_face_crop_not_the_whole_frame() -> None:
    frame = _textured_frame(base_value=180)
    seen_shapes: list[tuple[int, ...]] = []

    def _recording_classifier(crop: np.ndarray) -> tuple[bool, bool]:
        seen_shapes.append(crop.shape)
        return False, False

    compute_condition_flags(**_base_kwargs(frame), classifier=_recording_classifier)

    assert len(seen_shapes) == 1
    expected_h = int(_BBOX_WH[1])
    expected_w = int(_BBOX_WH[0])
    assert seen_shapes[0] == (expected_h, expected_w, 3)


# --- degenerate inputs ------------------------------------------------------


def test_degenerate_bbox_outside_frame_does_not_raise_and_defaults_false() -> None:
    frame = _solid_frame(gray_value=128)
    flags = compute_condition_flags(
        frame_bgr=frame,
        bbox_xy=(500.0, 500.0),  # entirely outside the 200x200 frame
        bbox_wh=(100.0, 100.0),  # both sides >= LOW_RES_MIN_PX
        left_eye=(500.0, 500.0),
        right_eye=(600.0, 500.0),
        left_mouth=(500.0, 600.0),
        right_mouth=(600.0, 600.0),
    )
    assert flags == {
        "dark": False,
        "blurry": False,
        "low_res": False,  # low_res is bbox-geometry-only -- still computed
        "masked": False,
        "sunglasses": False,
    }


def test_all_five_canonical_keys_always_present() -> None:
    frame = _solid_frame(gray_value=128)
    flags = compute_condition_flags(**_base_kwargs(frame))
    assert set(flags.keys()) == {"dark", "blurry", "low_res", "masked", "sunglasses"}
    assert all(isinstance(v, bool) for v in flags.values())


# --- merge_condition_flags --------------------------------------------------


def test_merge_condition_flags_is_logical_or() -> None:
    aggregate = {
        "dark": False, "blurry": False, "low_res": True, "masked": False, "sunglasses": False,
    }
    frame_flags = {
        "dark": True, "blurry": False, "low_res": False, "masked": False, "sunglasses": False,
    }
    merged = merge_condition_flags(aggregate, frame_flags)
    assert merged == {
        "dark": True,
        "blurry": False,
        "low_res": True,
        "masked": False,
        "sunglasses": False,
    }


def test_merge_condition_flags_never_unsets_a_true_flag() -> None:
    aggregate = {
        "dark": True, "blurry": True, "low_res": True, "masked": True, "sunglasses": True,
    }
    frame_flags = {
        "dark": False, "blurry": False, "low_res": False, "masked": False, "sunglasses": False,
    }
    merged = merge_condition_flags(aggregate, frame_flags)
    assert all(merged.values())


# --- overhead budget (<1ms/frame, EC-IN-01 acceptance criteria) ------------


def test_compute_condition_flags_overhead_under_one_millisecond() -> None:
    import time

    frame = _textured_frame(base_value=150)
    kwargs = _base_kwargs(frame)

    # Warm up (first call pays for lazy `import numpy` inside the module --
    # already imported at module scope here, but keep this robust to that
    # changing) before timing.
    compute_condition_flags(**kwargs)

    iterations = 200
    start = time.perf_counter()
    for _ in range(iterations):
        compute_condition_flags(**kwargs)
    elapsed = time.perf_counter() - start
    per_call_ms = (elapsed / iterations) * 1000
    assert per_call_ms < 1.0, f"condition-flag computation too slow: {per_call_ms:.4f} ms/frame"


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
