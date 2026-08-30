"""Vendored AdaFace backbone architecture (TR-06).

**Provenance / attribution (required by license)**: this module is a MINIMAL
port of `net.py` from the official AdaFace repository —
https://github.com/mk-minchul/adaface (MIT License) — the reference
implementation for:

    Minchul Kim, Anil K. Jain, Xiaoming Liu. "AdaFace: Quality Adaptive
    Margin for Face Recognition." CVPR 2022. arXiv:2204.00964.

Only the pieces this project actually uses are ported: the IR (non-SE)
`Backbone` variant, the `IR_50`/`IR_101` factory functions, and their
supporting blocks (`BasicBlockIR`, `BottleneckIR`, `get_blocks`,
`initialize_weights`, `Flatten`). The IR-SE variants and the 18/34/152/200
depth configurations from upstream `net.py` are deliberately NOT ported —
this project only ever loads `ir_50`/`ir_101` (mode `'ir'`), per
`documentation/research/recommendations.md` §2 — to keep the vendored
surface small and easy to audit against the upstream source.

This is a PORT OF ARCHITECTURE CODE ONLY. It does not include, and this
project does not claim ownership of, any trained weights — pretrained
checkpoints are procured separately (see `download_adaface_weights.py` /
the `ai-training download-adaface-weights` CLI command) directly from the
upstream authors' distribution, and remain governed by whatever license
the upstream project attaches to those specific weight files. See
`embedder.AdaFaceEmbedder` for the licensing/procurement decision record.

Note on `IR_101`: this is not a typo for "101 layers" — upstream's own
`IR_101(input_size)` factory calls `Backbone(input_size, 100, 'ir')`
(`num_layers=100`). The naming is upstream's, kept as-is here so weight
files and code both refer to the same thing.
"""

from __future__ import annotations

from collections import namedtuple

import torch
from torch import nn


class Flatten(nn.Module):
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x.view(x.size(0), -1)


class BasicBlockIR(nn.Module):
    """IR (non-SE) residual block used for `num_layers` <= 100 — i.e. both
    `ir_50` and `ir_101` (== num_layers 100) that this project uses."""

    def __init__(self, in_channel: int, depth: int, stride: int) -> None:
        super().__init__()
        if in_channel == depth:
            self.shortcut_layer: nn.Module = nn.MaxPool2d(1, stride)
        else:
            self.shortcut_layer = nn.Sequential(
                nn.Conv2d(in_channel, depth, (1, 1), stride, bias=False),
                nn.BatchNorm2d(depth),
            )
        self.res_layer = nn.Sequential(
            nn.BatchNorm2d(in_channel),
            nn.Conv2d(in_channel, depth, (3, 3), (1, 1), 1, bias=False),
            nn.BatchNorm2d(depth),
            nn.PReLU(depth),
            nn.Conv2d(depth, depth, (3, 3), stride, 1, bias=False),
            nn.BatchNorm2d(depth),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        shortcut = self.shortcut_layer(x)
        res = self.res_layer(x)
        return res + shortcut


class BottleneckIR(nn.Module):
    """IR (non-SE) bottleneck block — used upstream for `num_layers` > 100
    (152/200). Not exercised by `ir_50`/`ir_101` (both <= 100 -> use
    `BasicBlockIR` instead, see `Backbone.__init__`), but ported alongside
    it for architectural fidelity with upstream `net.py`."""

    def __init__(self, in_channel: int, depth: int, stride: int) -> None:
        super().__init__()
        reduction_channel = depth // 4
        if in_channel == depth:
            self.shortcut_layer: nn.Module = nn.MaxPool2d(1, stride)
        else:
            self.shortcut_layer = nn.Sequential(
                nn.Conv2d(in_channel, depth, (1, 1), stride, bias=False),
                nn.BatchNorm2d(depth),
            )
        self.res_layer = nn.Sequential(
            nn.BatchNorm2d(in_channel),
            nn.Conv2d(in_channel, reduction_channel, (1, 1), (1, 1), 0, bias=False),
            nn.BatchNorm2d(reduction_channel),
            nn.PReLU(reduction_channel),
            nn.Conv2d(reduction_channel, reduction_channel, (3, 3), (1, 1), 1, bias=False),
            nn.BatchNorm2d(reduction_channel),
            nn.PReLU(reduction_channel),
            nn.Conv2d(reduction_channel, depth, (1, 1), stride, 0, bias=False),
            nn.BatchNorm2d(depth),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        shortcut = self.shortcut_layer(x)
        res = self.res_layer(x)
        return res + shortcut


class _Bottleneck(namedtuple("_Bottleneck", ["in_channel", "depth", "stride"])):
    """A named tuple describing one residual unit's channel/stride config."""


def _get_block(in_channel: int, depth: int, num_units: int, stride: int = 2) -> list[_Bottleneck]:
    return [_Bottleneck(in_channel, depth, stride)] + [
        _Bottleneck(depth, depth, 1) for _ in range(num_units - 1)
    ]


def get_blocks(num_layers: int) -> list[list[_Bottleneck]]:
    """Per-stage unit configs. Only 50 and 100 are ported (the only depths
    `ir_50`/`ir_101` need) — upstream also defines 18/34/152/200."""
    if num_layers == 50:
        return [
            _get_block(in_channel=64, depth=64, num_units=3),
            _get_block(in_channel=64, depth=128, num_units=4),
            _get_block(in_channel=128, depth=256, num_units=14),
            _get_block(in_channel=256, depth=512, num_units=3),
        ]
    if num_layers == 100:
        return [
            _get_block(in_channel=64, depth=64, num_units=3),
            _get_block(in_channel=64, depth=128, num_units=13),
            _get_block(in_channel=128, depth=256, num_units=30),
            _get_block(in_channel=256, depth=512, num_units=3),
        ]
    raise ValueError(f"get_blocks: unsupported num_layers={num_layers} (only 50/100 are ported)")


def initialize_weights(modules: list[nn.Module] | nn.Module) -> None:
    """Kaiming/constant init matching upstream `net.py::initialize_weights`
    — only exercised when building a model WITHOUT a pretrained checkpoint
    (e.g. the architecture-only unit test); real inference always loads a
    trained `state_dict` afterwards, overwriting these values."""
    for module in modules.modules() if isinstance(modules, nn.Module) else modules:
        if isinstance(module, nn.Conv2d):
            nn.init.kaiming_normal_(module.weight, mode="fan_out", nonlinearity="relu")
            if module.bias is not None:
                module.bias.data.zero_()
        elif isinstance(module, (nn.BatchNorm2d, nn.BatchNorm1d)):
            # `affine=False` BatchNorm1d (the output_layer's final norm) has
            # no learnable weight/bias to initialize.
            if module.weight is not None:
                module.weight.data.fill_(1)
            if module.bias is not None:
                module.bias.data.zero_()
        elif isinstance(module, nn.Linear):
            nn.init.kaiming_normal_(module.weight, mode="fan_out", nonlinearity="relu")
            if module.bias is not None:
                module.bias.data.zero_()


class Backbone(nn.Module):
    """IR-ResNet face embedding backbone (mode `'ir'` only — the IR-SE
    variant from upstream is not ported, this project doesn't use it).

    Forward pass returns `(output, norm)` where `output` is ALREADY
    L2-normalized (`output = x / norm`) — callers must NOT re-normalize.
    """

    def __init__(self, input_size: tuple[int, int], num_layers: int, mode: str = "ir") -> None:
        super().__init__()
        assert input_size[0] in (112, 224), "input_size should be (112, 112) or (224, 224)"
        assert num_layers in (50, 100), "only num_layers 50/100 are ported (ir_50/ir_101)"
        assert mode == "ir", "only mode='ir' is ported (IR-SE variants unused by this project)"

        blocks = get_blocks(num_layers)
        unit_module = BasicBlockIR  # upstream: BasicBlockIR for num_layers <= 100

        self.input_layer = nn.Sequential(
            nn.Conv2d(3, 64, (3, 3), 1, 1, bias=False),
            nn.BatchNorm2d(64),
            nn.PReLU(64),
        )
        if input_size[0] == 112:
            output_channel = 512 * 7 * 7
        else:  # 224
            output_channel = 512 * 14 * 14
        self.output_layer = nn.Sequential(
            nn.BatchNorm2d(512),
            nn.Dropout(0.4),
            Flatten(),
            nn.Linear(output_channel, 512),
            nn.BatchNorm1d(512, affine=False),
        )

        modules = []
        for block in blocks:
            for unit in block:
                modules.append(unit_module(unit.in_channel, unit.depth, unit.stride))
        self.body = nn.Sequential(*modules)

        initialize_weights(self.modules())

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        x = self.input_layer(x)
        x = self.body(x)
        x = self.output_layer(x)
        norm = torch.norm(x, 2, 1, True)
        output = torch.div(x, norm)
        return output, norm


def IR_50(input_size: tuple[int, int]) -> Backbone:  # noqa: N802 - upstream naming kept verbatim
    return Backbone(input_size, 50, "ir")


def IR_101(input_size: tuple[int, int]) -> Backbone:  # noqa: N802 - upstream naming kept verbatim
    """See module docstring: upstream `IR_101` builds `num_layers=100`, not
    101 — this is upstream's own naming, not a bug introduced here."""
    return Backbone(input_size, 100, "ir")


_ARCH_FACTORIES = {
    "ir_50": IR_50,
    "ir_101": IR_101,
}


def build_model(arch: str, input_size: tuple[int, int] = (112, 112)) -> Backbone:
    """Construct an untrained `Backbone` for `arch` ('ir_50' or 'ir_101').

    Weights are NOT loaded here — callers (`embedder.AdaFaceEmbedder`) load
    a `state_dict` afterwards. Kept separate so architecture-only tests
    (no checkpoint file needed) can call this directly.
    """
    try:
        factory = _ARCH_FACTORIES[arch]
    except KeyError as exc:
        raise ValueError(
            f"build_model: unsupported arch={arch!r}, expected one of {sorted(_ARCH_FACTORIES)}"
        ) from exc
    return factory(input_size)
