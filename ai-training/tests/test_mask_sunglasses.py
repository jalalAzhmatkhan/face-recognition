"""EC-IN-03 (TSD-edge-cases.md C-2/OQ-4): `ai_training.classifiers.mask_sunglasses`.

Needs the `ml` extra (`torch`, `onnx`, `onnxruntime`) -- skipped entirely on
base CI, same convention as `test_minifasnet_net.py`/`test_adaface_net.py`.

Per the module's own docstring: these tests verify the training/eval/export
loop runs MECHANICALLY end-to-end on synthetic (random) data -- they do NOT
and cannot assert anything about real classification accuracy, which needs
real masked/sunglasses/none data this sandbox does not have.
"""

from __future__ import annotations

import time

import pytest

torch = pytest.importorskip("torch")
onnxruntime = pytest.importorskip("onnxruntime")

import numpy as np  # noqa: E402

from ai_training.classifiers.mask_sunglasses import (  # noqa: E402
    LABEL_NAMES,
    build_model,
    build_synthetic_dataset,
    evaluate_synthetic_smoke,
    export_onnx,
    train_synthetic_smoke,
)

_IMG_SIZE = 96


def test_build_model_forward_shape() -> None:
    model = build_model(img_size=_IMG_SIZE)
    x = torch.rand((4, 3, _IMG_SIZE, _IMG_SIZE))

    logits = model(x)

    assert logits.shape == (4, len(LABEL_NAMES))
    assert torch.isfinite(logits).all()


def test_train_synthetic_smoke_runs_and_stays_finite() -> None:
    model = build_model(img_size=_IMG_SIZE)
    dataset = build_synthetic_dataset(64, img_size=_IMG_SIZE, seed=0)

    result = train_synthetic_smoke(model, dataset, epochs=3, batch_size=16)

    assert len(result.epoch_losses) == 3
    assert all(np.isfinite(loss) for loss in result.epoch_losses)


def test_evaluate_synthetic_smoke_returns_finite_loss() -> None:
    model = build_model(img_size=_IMG_SIZE)
    dataset = build_synthetic_dataset(32, img_size=_IMG_SIZE, seed=1)
    train_synthetic_smoke(model, dataset, epochs=1, batch_size=16)

    loss = evaluate_synthetic_smoke(model, dataset)

    assert np.isfinite(loss)


def test_export_onnx_round_trips_through_onnxruntime(tmp_path) -> None:
    model = build_model(img_size=_IMG_SIZE)
    onnx_path = tmp_path / "mask_sunglasses.onnx"

    export_onnx(model, onnx_path, img_size=_IMG_SIZE)

    assert onnx_path.exists()
    session = onnxruntime.InferenceSession(
        str(onnx_path), providers=["CPUExecutionProvider"]
    )
    x = np.random.default_rng(0).random((1, 3, _IMG_SIZE, _IMG_SIZE)).astype(np.float32)

    (onnx_logits,) = session.run(None, {"crop": x})

    assert onnx_logits.shape == (1, len(LABEL_NAMES))
    # Cross-check against the original torch model's own forward pass on
    # the exact same input -- the exported graph must compute the SAME
    # function, not merely "some" function that happens to run.
    model.eval()
    with torch.no_grad():
        torch_logits = model(torch.from_numpy(x)).numpy()
    assert np.allclose(onnx_logits, torch_logits, atol=1e-4)


def test_export_onnx_accepts_dynamic_batch(tmp_path) -> None:
    model = build_model(img_size=_IMG_SIZE)
    onnx_path = tmp_path / "mask_sunglasses_batch.onnx"
    export_onnx(model, onnx_path, img_size=_IMG_SIZE)
    session = onnxruntime.InferenceSession(
        str(onnx_path), providers=["CPUExecutionProvider"]
    )

    x = np.random.default_rng(1).random((5, 3, _IMG_SIZE, _IMG_SIZE)).astype(np.float32)
    (onnx_logits,) = session.run(None, {"crop": x})

    assert onnx_logits.shape == (5, len(LABEL_NAMES))


def test_onnxruntime_single_thread_latency_budget(tmp_path) -> None:
    """Sanity-checks the architecture+ONNX-Runtime overhead itself stays
    well inside the <=3ms CPU/crop budget (TSD-edge-cases.md C-2), using an
    UNTRAINED (random-weight) exported model -- legitimate for a latency
    measurement (architecture + runtime cost is identical regardless of
    whether the weights are trained), NOT for an accuracy claim. Mirrors
    `ai_inference.pipeline.mask_sunglasses`'s own (real serving-path)
    latency test -- kept here too so a training-side change to the
    architecture that blows the budget is caught before it ever reaches
    ai-inference.
    """
    model = build_model(img_size=_IMG_SIZE)
    onnx_path = tmp_path / "mask_sunglasses_latency.onnx"
    export_onnx(model, onnx_path, img_size=_IMG_SIZE)

    session_options = onnxruntime.SessionOptions()
    session_options.intra_op_num_threads = 1
    session = onnxruntime.InferenceSession(
        str(onnx_path), sess_options=session_options, providers=["CPUExecutionProvider"]
    )
    x = np.random.default_rng(2).random((1, 3, _IMG_SIZE, _IMG_SIZE)).astype(np.float32)

    # Warm up (first call pays one-time graph-optimization/allocation cost
    # that a long-running service would never re-pay per request).
    for _ in range(5):
        session.run(None, {"crop": x})

    n_runs = 50
    start = time.perf_counter()
    for _ in range(n_runs):
        session.run(None, {"crop": x})
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    per_crop_ms = elapsed_ms / n_runs
    assert per_crop_ms <= 3.0, f"per-crop latency {per_crop_ms:.3f}ms exceeds 3ms budget"
