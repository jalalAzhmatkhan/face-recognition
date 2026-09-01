"""Synthetic masked-face overlay abstraction (A-4, TSD-edge-cases.md A-4 /
Sec.6 Keputusan Desain OQ-1).

Defines the seam (`MaskOverlayProvider`) the A-4 pipeline
(`ai_training.embedding.synthetic_masked`) depends on, plus the intended
real backend (`MaskTheFaceProvider`, wrapping
github.com/aqeelanwar/MaskTheFace, MIT license). This module is imported
eagerly by `ai_training.worker.tasks` (it must be safe to import with no
extra dependencies installed) — everything dlib-specific is deferred to
inside `MaskTheFaceProvider.apply()`.

**SANDBOX STATUS, verified 2026-09-01 (documented, not fabricated — see
task instructions)**: MaskTheFace is a script-based GitHub project, not a
published PyPI package (`https://pypi.org/simple/masktheface/` -> HTTP
404), so using it means vendoring its masking source directly rather than
`uv add`-ing it. Its core dependency `dlib` (Boost License — OQ-1's
accepted choice, "aman internal use") ships **no prebuilt wheel for any
platform** on PyPI — `https://pypi.org/pypi/dlib/json` lists only a
`dlib-20.0.1.tar.gz` sdist — and must be compiled from source with CMake +
a C++ toolchain. This sandbox has CMake (`cmake.exe` on PATH) but no
`cl.exe` (MSVC) or `g++` on PATH, so building dlib from source is not
possible in this environment/session. Consequently `MaskTheFaceProvider`
below is real, integration-shaped code, but its `.apply()` always raises
`RuntimeError` here — this is the "graceful degradation" case the A-4
pipeline is explicitly built to handle (see
`ai_training.embedding.synthetic_masked.generate_synthetic_masked_templates`'s
docstring): a raise from this provider is treated as "zero synthetic
templates for this enrollment", never as a fatal QC/enrollment failure.

**To make this real** in an environment with a full ML toolchain:
1. Install `dlib` (`pip install dlib` in an environment with CMake +
   MSVC/gcc, or `conda install -c conda-forge dlib` for a prebuilt binary
   — conda-forge does publish binaries even though PyPI does not).
2. Vendor MaskTheFace's `utils/aux_functions.py::mask_face` (MIT) into
   this package (e.g. `ai_training/quality/_masktheface_vendor.py`) and
   download its `shape_predictor_68_face_landmarks.dat` model asset (same
   "committed model asset, not fetched at runtime" pattern already used
   for `models/face_landmarker.task` — see `quality/pose.py`).
3. Replace the `raise RuntimeError(...)` in `MaskTheFaceProvider.apply()`
   with a call into that vendored function, mapping `mask_type` ("surgical"
   -> MaskTheFace's `"surgical_blue"`/`"surgical_white"` template,
   "cloth_dark" -> its `"cloth"` template recolored/selected dark) with
   `full_coverage` (nose-covering) mask assets per TSD A-4's requirement.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# TSD A-4 / OQ-1: exactly 2 mask types, both full-coverage over the nose
# (coverage of the nose is the "variable dominan" per NIST IR 8311, cited
# in TSD A-4). Order is also the round-robin assignment order used by
# `ai_training.embedding.synthetic_masked.generate_synthetic_masked_templates`.
MASK_TYPES: tuple[str, ...] = ("surgical", "cloth_dark")


@runtime_checkable
class MaskOverlayProvider(Protocol):
    """The A-4 pipeline depends on this, never on a concrete backend
    class — lets tests substitute a fake without touching dlib/MaskTheFace
    at all (mirrors `embedding.embedder.EmbedderInterface`'s role for the
    embedding backend)."""

    def apply(self, frame_bgr: Any, mask_type: str) -> Any | None:
        """Return a COPY of `frame_bgr` with a full-nose-coverage synthetic
        mask of `mask_type` (one of `MASK_TYPES`) overlaid, or `None` if
        the overlay could not be applied to this particular frame (e.g. no
        face/landmarks found in it). Must NEVER mutate `frame_bgr` in
        place — callers may still need the original frame afterwards.

        A raise from this method (any exception, not just `RuntimeError`)
        is a valid outcome the caller MUST treat as "skip this one
        source-frame/mask-type combination", never as a fatal pipeline
        error — see `generate_synthetic_masked_templates`'s docstring.
        """
        ...


class MaskTheFaceProvider:
    """Real A-4 backend (MaskTheFace, MIT + dlib, Boost — OQ-1). See this
    module's docstring for its current sandbox status: `.apply()` always
    raises `RuntimeError` in THIS environment because `dlib` cannot be
    installed here (no PyPI wheel, no local C++ toolchain) and
    MaskTheFace's masking source has not been vendored into the repo.
    """

    def apply(self, frame_bgr: Any, mask_type: str) -> Any | None:
        if mask_type not in MASK_TYPES:
            raise ValueError(f"unknown mask_type {mask_type!r}, expected one of {MASK_TYPES}")
        self._require_dlib()
        # Unreachable today (the line above always raises when dlib is
        # absent) -- kept as the explicit landing spot for the vendored
        # MaskTheFace call described in the module docstring's "to make
        # this real" steps, so that future change is a small, obvious
        # diff instead of a rewrite of this class.
        raise RuntimeError(  # pragma: no cover - only reached if dlib IS installed
            "MaskTheFaceProvider.apply() has a working dlib import but MaskTheFace's masking "
            "source has not been vendored into this repo yet -- see this module's docstring "
            "('To make this real') for the two remaining steps."
        )

    @staticmethod
    def _require_dlib() -> Any:
        try:
            import dlib  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "MaskTheFaceProvider requires 'dlib' (Boost License, TSD-edge-cases.md OQ-1), "
                "which is not installed in this environment. dlib has no prebuilt PyPI wheel for "
                "any platform (sdist-only) and must be built from source with CMake + a C++ "
                "toolchain (MSVC/gcc) -- see ai_training.quality.mask_overlay's module docstring "
                "for the verified sandbox status and how to make this real."
            ) from exc
        return dlib


def build_mask_overlay_provider() -> MaskOverlayProvider:
    """Factory mirroring `embedding.embedder.build_embedder` /
    `liveness.detector`'s backend-selection shape. Only one backend exists
    today (`MaskTheFaceProvider`, A-4's chosen tool per OQ-1) so there is
    no settings-driven branch yet -- this function exists so callers (and
    tests) have one seam to swap in a fake, matching the rest of this
    codebase's provider-factory convention.
    """
    return MaskTheFaceProvider()
