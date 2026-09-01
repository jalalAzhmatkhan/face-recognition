"""Synthetic placeholder slice generation (EC-TR-01) - pure numpy, no `ml`
extra needed."""

from __future__ import annotations

import numpy as np
import pytest

from ai_training.evaluation.synthetic_slices import (
    AUGMENTATIONS,
    CROP_SIZE,
    apply_blur,
    apply_dark,
    apply_low_res,
    apply_synthetic_mask,
    build_synthetic_slice_crops,
    make_base_identity_crop,
    make_probe_variant,
)


def test_base_identity_crop_is_deterministic_per_identity() -> None:
    first = make_base_identity_crop("alice")
    second = make_base_identity_crop("alice")
    assert np.array_equal(first, second)
    assert first.shape == (CROP_SIZE, CROP_SIZE, 3)
    assert first.dtype == np.uint8


def test_base_identity_crop_differs_across_identities() -> None:
    alice = make_base_identity_crop("alice")
    bob = make_base_identity_crop("bob")
    assert not np.array_equal(alice, bob)


def test_probe_variant_is_deterministic_and_close_to_base() -> None:
    variant = make_probe_variant("alice", 0)
    base = make_base_identity_crop("alice")
    assert np.array_equal(variant, make_probe_variant("alice", 0))
    # Noise is bounded to +-10 per the docstring.
    diff = np.abs(variant.astype(np.int16) - base.astype(np.int16))
    assert diff.max() <= 10


def test_probe_variants_differ_by_index() -> None:
    v0 = make_probe_variant("alice", 0)
    v1 = make_probe_variant("alice", 1)
    assert not np.array_equal(v0, v1)


def test_apply_dark_reduces_mean_brightness() -> None:
    crop = np.full((CROP_SIZE, CROP_SIZE, 3), 200, dtype=np.uint8)
    darkened = apply_dark(crop, factor=0.25)
    assert darkened.mean() == pytest.approx(50.0, abs=1.0)


def test_apply_blur_preserves_shape_and_smooths_a_sharp_edge() -> None:
    crop = np.zeros((CROP_SIZE, CROP_SIZE, 3), dtype=np.uint8)
    crop[:, CROP_SIZE // 2 :, :] = 255  # sharp vertical edge
    blurred = apply_blur(crop, kernel_size=7)
    assert blurred.shape == crop.shape
    # A pixel adjacent to the edge should no longer be pure black/white.
    edge_col = CROP_SIZE // 2
    assert 0 < blurred[CROP_SIZE // 2, edge_col, 0] < 255


def test_apply_blur_rejects_even_kernel() -> None:
    crop = np.zeros((CROP_SIZE, CROP_SIZE, 3), dtype=np.uint8)
    with pytest.raises(ValueError):
        apply_blur(crop, kernel_size=4)


def test_apply_low_res_preserves_shape() -> None:
    crop = make_base_identity_crop("alice")
    result = apply_low_res(crop, downscale_factor=4)
    assert result.shape == crop.shape


def test_apply_low_res_produces_blocky_output() -> None:
    crop = make_base_identity_crop("alice")
    result = apply_low_res(crop, downscale_factor=4)
    # Every 4x4 block should be constant (nearest-neighbor upsample of a
    # block-averaged downsample).
    block = result[0:4, 0:4, 0]
    assert np.all(block == block[0, 0])


def test_apply_synthetic_mask_leaves_upper_half_untouched_and_flat_fills_lower() -> None:
    crop = make_base_identity_crop("alice")
    masked = apply_synthetic_mask(crop, coverage=0.5)
    assert np.array_equal(masked[:56, :, :], crop[:56, :, :])
    assert np.all(masked[56:, :, :] == 128)


def test_apply_synthetic_mask_rejects_out_of_range_coverage() -> None:
    crop = make_base_identity_crop("alice")
    with pytest.raises(ValueError):
        apply_synthetic_mask(crop, coverage=1.5)


def test_build_synthetic_slice_crops_rejects_non_synthesizable_slice() -> None:
    with pytest.raises(ValueError):
        build_synthetic_slice_crops("hijab", n_identities=3, probes_per_identity=2)


def test_build_synthetic_slice_crops_shapes_and_disjoint_identities() -> None:
    genuine, impostor = build_synthetic_slice_crops("dark", n_identities=5, probes_per_identity=3)
    assert set(genuine.keys()) == {f"synthetic-genuine-{i:03d}" for i in range(5)}
    for crops in genuine.values():
        assert len(crops) == 3
        for crop in crops:
            assert crop.shape == (CROP_SIZE, CROP_SIZE, 3)
    assert len(impostor) == 5
    genuine_ids = set(genuine.keys())
    impostor_source_ids = {f"synthetic-impostor-{i:03d}" for i in range(5)}
    assert genuine_ids.isdisjoint(impostor_source_ids)


def test_all_catalog_synthesizable_slices_have_an_augmentation() -> None:
    from ai_training.evaluation.slices import SLICE_CATALOG

    synthesizable = {name for name, spec in SLICE_CATALOG.items() if spec.synthesizable}
    assert synthesizable == set(AUGMENTATIONS)
