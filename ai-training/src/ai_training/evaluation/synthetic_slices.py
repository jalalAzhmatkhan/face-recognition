"""Small synthetic placeholder slices for the EC-TR-01 harness smoke test.

**What this module IS**: pure-numpy image degradation (no opencv/PIL/torch,
so it runs on base CI without the `ml` extra - same "importable everywhere"
requirement as `ai_training.evaluation.scoring`) applied to algorithmically
generated placeholder crops, used ONLY to prove the harness's
compute/aggregate/report path (slices -> gallery/probe split -> stub
embed+liveness -> CI/bootstrap -> gate check) actually runs end-to-end.

**What this module is NOT**: a source of real face-recognition accuracy
numbers, and not a substitute for EC-OPS-02's real data collection. Two
independent reasons, both documented here rather than glossed over:

1. There is no committed face-image fixture ANYWHERE in this repository
   (`qa/fixtures/` is an empty placeholder directory as of this task) to
   degrade in the first place, so "genuine identity" here means a
   deterministic-but-arbitrary numpy pattern seeded from a hash of the
   identity string - NOT a real face, not even a low-quality one.
2. `ai_training.embedding.embedder.StubEmbedder` and
   `ai_training.liveness.detector.StubLivenessDetector` (the only embedder/
   liveness backends available without the `ml` extra + real pretrained
   weights, neither of which this sandbox has) hash raw pixel bytes into a
   pseudo-random vector/score - by design they carry NO visual signal at
   all (see their docstrings). Recall/Precision/liveness-pass-rate computed
   against them is chance-level noise, not evidence about real robustness.

Only the slices TSD-EC D-7.1 lists as plausibly synthesizable from generic
image processing (`dark`, `blur`, `low-res`, `masked-sintetis` - see
`ai_training.evaluation.slices.SLICE_CATALOG[...].synthesizable`) get a
generator here. `masked-riil`, `hijab`, `kacamata`, `per-demografi-utama`,
`kontak-kosmetik` genuinely need real human subjects and are NOT attempted -
use `ai_training.evaluation.slices.skeleton_manifest` for those.
"""

from __future__ import annotations

import hashlib

import numpy as np

CROP_SIZE = 112  # matches EmbedderInterface's documented 112x112 aligned-crop contract


def _seed_from(*parts: str) -> int:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def make_base_identity_crop(identity: str) -> np.ndarray:
    """A deterministic `(112, 112, 3)` uint8 placeholder "face" for
    `identity` - same identity always yields the same base pattern (so
    augmented probes of the same identity share a recognizable base
    pattern), different identities are independent random fields."""
    rng = np.random.default_rng(_seed_from("identity", identity))
    return rng.integers(0, 256, size=(CROP_SIZE, CROP_SIZE, 3), dtype=np.uint8)


def make_probe_variant(identity: str, probe_index: int) -> np.ndarray:
    """A "clean" (no degradation applied yet) probe crop for `identity`:
    the base identity pattern with a small amount of per-probe noise, so
    repeated probes of one identity are similar-but-not-byte-identical
    (mimicking distinct captures of the same person) while staying
    deterministic given `(identity, probe_index)`."""
    base = make_base_identity_crop(identity).astype(np.int16)
    rng = np.random.default_rng(_seed_from("probe", identity, str(probe_index)))
    noise = rng.integers(-10, 11, size=base.shape, dtype=np.int16)
    return np.clip(base + noise, 0, 255).astype(np.uint8)


def apply_dark(crop: np.ndarray, factor: float = 0.25) -> np.ndarray:
    """Simulate a low-light capture: linear brightness scale-down.
    `factor=0.25` means the frame ends up at ~25% of its original mean-luma,
    comfortably below `QCSettings.brightness_min` for a mid-gray input."""
    scaled = crop.astype(np.float64) * factor
    return np.clip(scaled, 0, 255).astype(np.uint8)


def apply_blur(crop: np.ndarray, kernel_size: int = 7) -> np.ndarray:
    """Simulate motion/focus blur via a manual box filter (uniform
    convolution), implemented with plain numpy cumulative sums rather than
    `cv2.blur`/`scipy.ndimage` - same "stay importable without heavy deps"
    reasoning as `ai_training.quality.metrics`'s manual variance-of-Laplacian.
    Edge pixels use a reflect-padded window so the output stays `(H, W, 3)`.
    """
    if kernel_size < 1 or kernel_size % 2 == 0:
        raise ValueError("apply_blur: kernel_size must be a positive odd integer")
    pad = kernel_size // 2
    padded = np.pad(crop.astype(np.float64), ((pad, pad), (pad, pad), (0, 0)), mode="reflect")
    out = np.zeros_like(crop, dtype=np.float64)
    h, w, _ = crop.shape
    for dy in range(kernel_size):
        for dx in range(kernel_size):
            out += padded[dy : dy + h, dx : dx + w, :]
    out /= kernel_size * kernel_size
    return np.clip(out, 0, 255).astype(np.uint8)


def apply_low_res(crop: np.ndarray, downscale_factor: int = 4) -> np.ndarray:
    """Simulate a low-resolution capture: block-average downsample then
    nearest-neighbor upsample back to `CROP_SIZE` (the information loss of a
    small sensor crop, not a real re-imaging - adequate for exercising the
    harness's low-res slice path, not for measuring real degradation)."""
    h, w, c = crop.shape
    if h % downscale_factor or w % downscale_factor:
        raise ValueError("apply_low_res: crop dimensions must divide downscale_factor")
    small_h, small_w = h // downscale_factor, w // downscale_factor
    reshaped = crop.reshape(small_h, downscale_factor, small_w, downscale_factor, c)
    downsampled = reshaped.mean(axis=(1, 3))
    upsampled = np.repeat(
        np.repeat(downsampled, downscale_factor, axis=0), downscale_factor, axis=1
    )
    return np.clip(upsampled, 0, 255).astype(np.uint8)


def apply_synthetic_mask(crop: np.ndarray, coverage: float = 0.5) -> np.ndarray:
    """Simulate a MaskTheFace-style occlusion: flat-fill the lower
    `coverage` fraction of the crop (a crude stand-in for a real masked
    warp/texture composite - MaskTheFace itself needs dlib landmarks and
    real face geometry, out of scope for a fixture-less placeholder)."""
    if not 0.0 < coverage < 1.0:
        raise ValueError("apply_synthetic_mask: coverage must be in (0, 1)")
    out = crop.copy()
    h = crop.shape[0]
    mask_start = int(h * (1 - coverage))
    # Mid-gray-ish flat fill, not derived from the underlying pixels -
    # deliberately destroys lower-face signal the way an actual mask would
    # occlude the mouth/nose/chin region from a recognition standpoint.
    out[mask_start:, :, :] = 128
    return out


AUGMENTATIONS = {
    "dark": apply_dark,
    "blur": apply_blur,
    "low-res": apply_low_res,
    "masked-sintetis": apply_synthetic_mask,
}


def build_synthetic_slice_crops(
    slice_name: str,
    *,
    n_identities: int,
    probes_per_identity: int,
) -> tuple[dict[str, list[np.ndarray]], list[np.ndarray]]:
    """Generate a small synthetic slice in memory.

    Returns `(genuine_crops_by_identity, impostor_crops)`:
    - `genuine_crops_by_identity[identity]` is `probes_per_identity` degraded
      variants of that identity's base pattern (the augmentation named by
      `slice_name` is applied to each).
    - `impostor_crops` is `n_identities` degraded crops of identities that
      never appear in `genuine_crops_by_identity` (disjoint identity space),
      one per synthesized impostor "identity" - the harness's caller decides
      how many pairwise gallery comparisons that yields (see
      `ai_training.evaluation.e2e`).

    Raises `ValueError` for a slice name not in `AUGMENTATIONS` (i.e. one of
    the non-synthesizable slices - `masked-riil`/`hijab`/`kacamata`/
    `per-demografi-utama`/`kontak-kosmetik` - use `slices.skeleton_manifest`
    for those instead).
    """
    if slice_name not in AUGMENTATIONS:
        raise ValueError(
            f"build_synthetic_slice_crops: slice '{slice_name}' is not synthesizable "
            f"from generic augmentation; supported: {sorted(AUGMENTATIONS)}. Use "
            "ai_training.evaluation.slices.skeleton_manifest for real-subject slices."
        )
    augment = AUGMENTATIONS[slice_name]

    genuine: dict[str, list[np.ndarray]] = {}
    for i in range(n_identities):
        identity = f"synthetic-genuine-{i:03d}"
        genuine[identity] = [
            augment(make_probe_variant(identity, p)) for p in range(probes_per_identity)
        ]

    impostor: list[np.ndarray] = []
    for i in range(n_identities):
        identity = f"synthetic-impostor-{i:03d}"
        impostor.append(augment(make_probe_variant(identity, 0)))

    return genuine, impostor
