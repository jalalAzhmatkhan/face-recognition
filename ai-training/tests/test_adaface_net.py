"""Vendored AdaFace backbone porting sanity checks (TR-06).

These tests build the architecture with RANDOM (untrained) weights — no
checkpoint file, no network — and only assert STRUCTURAL correctness
(output shape, L2-normalization). A shape mismatch is the most common
symptom of a porting bug (wrong depth/stride table, wrong block type,
wrong output_layer flatten size), so this is exactly what these tests
guard against. Requires the `ml` extra (torch).
"""

import pytest

torch = pytest.importorskip("torch")

from ai_training.embedding.adaface_net import build_model  # noqa: E402


def test_ir50_forward_shape_and_normalization() -> None:
    model = build_model("ir_50")
    model.eval()
    dummy = torch.randn(1, 3, 112, 112)
    with torch.no_grad():
        output, norm = model(dummy)
    assert output.shape == (1, 512)
    assert norm.shape == (1, 1)
    row_norm = torch.norm(output, p=2, dim=1)
    assert torch.allclose(row_norm, torch.ones_like(row_norm), atol=1e-4)


def test_ir101_forward_shape_and_normalization() -> None:
    # "ir_101" -> num_layers=100 internally (upstream naming, not a typo —
    # see adaface_net module docstring / IR_101).
    model = build_model("ir_101")
    model.eval()
    dummy = torch.randn(2, 3, 112, 112)
    with torch.no_grad():
        output, norm = model(dummy)
    assert output.shape == (2, 512)
    assert norm.shape == (2, 1)
    row_norm = torch.norm(output, p=2, dim=1)
    assert torch.allclose(row_norm, torch.ones_like(row_norm), atol=1e-4)


def test_build_model_rejects_unknown_arch() -> None:
    import pytest

    with pytest.raises(ValueError, match="unsupported arch"):
        build_model("ir_152")
