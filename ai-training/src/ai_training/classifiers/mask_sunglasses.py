"""EC-IN-03 (TSD-edge-cases.md C-2, OQ-4): own-model masked/sunglasses/none
classifier that replaces EC-IN-01's placeholder landmark-intensity
heuristic (`ai_inference.pipeline.condition_flags`'s `masked`/`sunglasses`
flags).

**Design (TSD-edge-cases.md C-2/OQ-4, verbatim)**: "classifier 3-kelas
tunggal milik sendiri (`{masked, sunglasses, none}`, multi-label) --
MobileNetV3-Small / ShuffleNetV2-0.5 / CNN 4-layer custom pada crop wajah
64x64-96x96, ONNX Runtime single-thread, +-1-3 ms CPU ... HINDARI detektor
YOLOv5/v8 (GPL/AGPL)". This module implements the "CNN 4-layer custom"
option explicitly listed as an alternative to the torchvision
MobileNetV3-Small/ShuffleNetV2 options: a small, from-scratch 4-conv-block
CNN, trained from random init (no pretrained weights, so there is zero
weight-licensing question -- unlike `ai_training.liveness.minifasnet_net`'s
vendored Apache-2.0 checkpoints or the AdaFace non-commercial-license
weights). Kept intentionally tiny (4 conv blocks + global-average-pool +
one linear head) specifically to hit the <=3ms CPU/crop budget on
ONNX Runtime with `intra_op_num_threads=1` -- see
`ai_inference.pipeline.mask_sunglasses` for the inference-side wrapper that
actually measures this.

**3-class via 2-output multi-label** (per the design doc): `masked` and
`sunglasses` are independent sigmoid outputs (a person can plausibly wear
both at once); `none` is implicit when both are below threshold, exactly
as TSD-edge-cases.md phrases it ("`{masked, sunglasses, none}` ...
multi-label"). Trained with `BCEWithLogitsLoss` over the 2 raw logits.

**No GPL/AGPL dependency**: this module imports only `torch` (BSD-3-Clause)
-- no `torchvision`, no YOLO of any kind, no pretrained checkpoint. See
`ai_training/pyproject.toml`'s `ml` extra for the up-to-date dependency
license accounting.

**What this module does NOT claim**: an ARCHITECTURE + a mechanically
verified train/eval/export loop, not a trained, accurate model. Real
training requires the datasets TSD-edge-cases.md C-2 lists (own enrollment
frames, MaskTheFace synthetic overlays [EC-TR-02, dlib-blocked in this
sandbox per that task's own report], CelebA `Eyeglasses` attribute,
synthetic sunglasses augmentation, a few hundred local photos) plus real
training compute -- none of which this sandbox has. `build_synthetic_dataset`
below produces RANDOM tensors with RANDOM labels purely to exercise the
training/eval/export code paths end-to-end (this is standard practice for
verifying a training pipeline mechanically before real data lands); do not
read anything about classification accuracy into a loss computed against
synthetic labels.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import torch
    from torch.utils.data import Dataset

# Design doc's crop-size range (TSD-edge-cases.md C-2: "crop wajah
# 64x64-96x96"). 96 chosen as the default -- upper end of the range gives
# the 4-conv-block-with-stride-2-each architecture below a non-degenerate
# 6x6 spatial map right before global-average-pool (96 / 2**4 == 6); still
# comfortably inside the <=3ms CPU budget (measured in
# `ai_inference.pipeline.mask_sunglasses`'s own latency test).
DEFAULT_IMG_SIZE = 96

# Multi-label output order -- MUST match `LABEL_NAMES` everywhere this
# model's 2-logit output is consumed (training targets, ONNX output,
# `ai_inference.pipeline.mask_sunglasses`'s post-processing). "none" is
# deliberately NOT a model output: it is implicit (both flags False), per
# TSD-edge-cases.md C-2's "{masked, sunglasses, none} ... multi-label".
LABEL_NAMES: tuple[str, str] = ("masked", "sunglasses")

_ONNX_OPSET = 17
_ONNX_INPUT_NAME = "crop"
_ONNX_OUTPUT_NAME = "logits"


def _require_torch():
    """Lazy `torch` import -- this module (like `ai_training.liveness.*`,
    `ai_training.embedding.adaface_net`) lives under the `ml` extra; base
    CI / the package skeleton must import-succeed without `torch`
    installed. Raises the same `ModuleNotFoundError` `import torch` would,
    just deferred to call time instead of module-import time."""
    import torch

    return torch


def build_model(img_size: int = DEFAULT_IMG_SIZE) -> torch.nn.Module:  # noqa: F821
    """Builds a fresh (randomly initialized) `MaskSunglassesNet`.

    4 conv blocks (Conv2d -> BatchNorm2d -> ReLU), each stride-2, doubling
    channels (8 -> 16 -> 32 -> 64) starting from a deliberately narrow 8
    channels (this is a 2-output binary-flag classifier on a small crop,
    not a face-recognition embedder -- it needs far less capacity), then
    global-average-pool + a single `Linear(64, 2)` head producing raw
    logits for `LABEL_NAMES`. No pretrained weights anywhere (random init
    only) -- see module docstring for why that matters license-wise.
    """
    torch = _require_torch()
    import torch.nn as nn

    class _MaskSunglassesNet(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            channels = (3, 8, 16, 32, 64)
            blocks = []
            for in_c, out_c in zip(channels[:-1], channels[1:], strict=True):
                blocks.append(
                    nn.Sequential(
                        nn.Conv2d(in_c, out_c, kernel_size=3, stride=2, padding=1, bias=False),
                        nn.BatchNorm2d(out_c),
                        nn.ReLU(inplace=True),
                    )
                )
            self.features = nn.Sequential(*blocks)
            self.pool = nn.AdaptiveAvgPool2d(1)
            self.head = nn.Linear(channels[-1], len(LABEL_NAMES))

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            x = self.features(x)
            x = self.pool(x)
            x = torch.flatten(x, 1)
            return self.head(x)

    model = _MaskSunglassesNet()
    model.img_size = img_size  # type: ignore[attr-defined]
    return model


@dataclass(frozen=True)
class TrainResult:
    """Per-epoch mean training loss (`BCEWithLogitsLoss`) -- returned by
    `train_synthetic_smoke` purely so callers/tests can assert the loop ran
    the expected number of epochs and produced finite numbers; NOT a
    real-data accuracy signal (see module docstring)."""

    epoch_losses: list[float]


def build_synthetic_dataset(
    n_samples: int, img_size: int = DEFAULT_IMG_SIZE, *, seed: int = 0
) -> Dataset:
    """RANDOM crops + RANDOM multi-label targets, purely to exercise the
    training loop mechanically (see module docstring's "what this does NOT
    claim"). NOT real masked/sunglasses/none data of any kind."""
    torch = _require_torch()
    from torch.utils.data import TensorDataset

    generator = torch.Generator().manual_seed(seed)
    images = torch.rand((n_samples, 3, img_size, img_size), generator=generator)
    labels = torch.randint(
        0, 2, (n_samples, len(LABEL_NAMES)), generator=generator
    ).float()
    return TensorDataset(images, labels)


def train_synthetic_smoke(
    model: torch.nn.Module,  # noqa: F821
    dataset: Dataset,
    *,
    epochs: int = 3,
    batch_size: int = 16,
    learning_rate: float = 1e-3,
) -> TrainResult:
    """Runs `epochs` passes of a standard `BCEWithLogitsLoss` + Adam loop
    over `dataset`. Named `*_smoke` deliberately: this is a MECHANICAL
    pipeline check (does the forward/backward/step loop run without
    crashing, do losses stay finite), not a real training run -- see
    module docstring. Safe to point at real data later with the exact same
    function signature once a real `Dataset` is wired up.
    """
    torch = _require_torch()
    from torch.utils.data import DataLoader

    loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    loss_fn = torch.nn.BCEWithLogitsLoss()

    model.train()
    epoch_losses: list[float] = []
    for _epoch in range(epochs):
        running_loss = 0.0
        n_batches = 0
        for images, targets in loader:
            optimizer.zero_grad()
            logits = model(images)
            loss = loss_fn(logits, targets)
            loss.backward()
            optimizer.step()
            running_loss += float(loss.item())
            n_batches += 1
        epoch_losses.append(running_loss / max(n_batches, 1))
    return TrainResult(epoch_losses=epoch_losses)


def evaluate_synthetic_smoke(model: torch.nn.Module, dataset: Dataset) -> float:  # noqa: F821
    """Mean `BCEWithLogitsLoss` over `dataset` in eval mode (no grad) --
    same "mechanical check, not a real accuracy metric" caveat as
    `train_synthetic_smoke` (module docstring). Real evaluation belongs on
    EC-TR-01's edge-case benchmark slice harness once real data + a real
    trained checkpoint exist (task brief's stated acceptance-criteria
    path), not here.
    """
    torch = _require_torch()
    from torch.utils.data import DataLoader

    loader = DataLoader(dataset, batch_size=32, shuffle=False)
    loss_fn = torch.nn.BCEWithLogitsLoss()

    model.eval()
    total_loss = 0.0
    n_batches = 0
    with torch.no_grad():
        for images, targets in loader:
            logits = model(images)
            loss = loss_fn(logits, targets)
            total_loss += float(loss.item())
            n_batches += 1
    return total_loss / max(n_batches, 1)


def export_onnx(
    model: torch.nn.Module,  # noqa: F821
    output_path: str | Path,
    *,
    img_size: int = DEFAULT_IMG_SIZE,
    opset: int = _ONNX_OPSET,
) -> Path:
    """Exports `model` to ONNX for `ai_inference.pipeline.mask_sunglasses`'s
    ONNX Runtime wrapper (TSD-edge-cases.md C-2: "ONNX Runtime
    single-thread"). Dynamic batch axis only -- crop size is fixed per
    deployment (`img_size`), matching how the inference wrapper always
    resizes crops to one configured size before calling the session.

    Raw logits are exported (no sigmoid baked into the graph): the
    inference wrapper applies `sigmoid` + its own configurable thresholds
    post-`session.run`, so threshold tuning never requires re-exporting.
    """
    torch = _require_torch()

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    model.eval()
    dummy_input = torch.zeros((1, 3, img_size, img_size), dtype=torch.float32)
    torch.onnx.export(
        model,
        dummy_input,
        str(output_path),
        input_names=[_ONNX_INPUT_NAME],
        output_names=[_ONNX_OUTPUT_NAME],
        dynamic_axes={
            _ONNX_INPUT_NAME: {0: "batch"},
            _ONNX_OUTPUT_NAME: {0: "batch"},
        },
        opset_version=opset,
        # `dynamo=False`: pin to torch's legacy TorchScript-tracing exporter.
        # Newer torch (>=2.5-ish) defaults to the new dynamo-based exporter,
        # which additionally requires the `onnxscript` package (not declared
        # here -- it would be a 5th new dependency this task's scope doesn't
        # need); the legacy exporter is fully sufficient for this small,
        # control-flow-free CNN and only needs `torch` + `onnx` (both
        # already declared above).
        dynamo=False,
    )
    return output_path
