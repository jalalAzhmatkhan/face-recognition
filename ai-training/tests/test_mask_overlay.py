"""`ai_training.quality.mask_overlay` (A-4, TSD-edge-cases.md OQ-1) — pure
interface/contract tests, no real dlib/MaskTheFace needed or assumed."""

import pytest

from ai_training.quality.mask_overlay import (
    MASK_TYPES,
    MaskOverlayProvider,
    MaskTheFaceProvider,
    build_mask_overlay_provider,
)


def test_mask_types_is_exactly_two_full_coverage_types() -> None:
    # TSD A-4/OQ-1: exactly 2 mask types (surgical + kain gelap).
    assert MASK_TYPES == ("surgical", "cloth_dark")


def test_build_mask_overlay_provider_returns_masktheface_provider() -> None:
    provider = build_mask_overlay_provider()
    assert isinstance(provider, MaskTheFaceProvider)
    assert isinstance(provider, MaskOverlayProvider)


def test_apply_rejects_unknown_mask_type() -> None:
    provider = MaskTheFaceProvider()
    with pytest.raises(ValueError, match="unknown mask_type"):
        provider.apply(object(), "sunglasses")


def test_apply_raises_runtime_error_when_dlib_unavailable() -> None:
    """Documents the current, verified sandbox status (see module
    docstring): dlib has no PyPI wheel and this sandbox has no C++
    toolchain, so it cannot be installed here. If a future environment
    DOES have dlib installed, this test steps aside rather than asserting
    a false claim about that environment."""
    try:
        import dlib  # noqa: F401
    except ImportError:
        pass
    else:
        pytest.skip("dlib IS installed in this environment; sandbox-unavailable case N/A")
    provider = MaskTheFaceProvider()
    with pytest.raises(RuntimeError, match="dlib"):
        provider.apply(object(), "surgical")
