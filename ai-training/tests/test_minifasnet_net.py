"""Architecture-only forward-pass shape tests for the vendored MiniFASNet
port (IN-04) -- random weights, no real checkpoint needed. Skips cleanly on
base CI (no `ml` extra, no torch)."""

import pytest

pytest.importorskip("torch")

import torch  # noqa: E402

from ai_training.liveness.minifasnet_net import MiniFASNetV1SE, MiniFASNetV2  # noqa: E402

_CONV6_KERNEL = (5, 5)  # required for 80x80 input, see detector.py._get_kernel


def test_minifasnet_v2_forward_pass_shape() -> None:
    model = MiniFASNetV2(conv6_kernel=_CONV6_KERNEL)
    model.eval()
    dummy = torch.randn(1, 3, 80, 80)
    with torch.no_grad():
        output = model(dummy)
    assert output.shape == (1, 3)


def test_minifasnet_v1se_forward_pass_shape() -> None:
    model = MiniFASNetV1SE(conv6_kernel=_CONV6_KERNEL)
    model.eval()
    dummy = torch.randn(1, 3, 80, 80)
    with torch.no_grad():
        output = model(dummy)
    assert output.shape == (1, 3)
