"""Real (not simulated) embedding-latency measurement (TR-07).

Pure orchestration/timing - only depends on `time` + `numpy` + the
`EmbedderInterface` contract (`ai_training.embedding.embedder`), so it runs
against `StubEmbedder` on base CI (no torch/mediapipe/opencv needed) and
against `AdaFaceEmbedder` when the `ml` extra + weights are available. It
does not know or care which concrete embedder it was given.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from ai_training.embedding.embedder import EmbedderInterface


def measure_embedding_latency_ms(
    embedder: EmbedderInterface, aligned_crops: list[Any]
) -> dict[str, float]:
    """Call `embedder.embed()` once per crop in `aligned_crops`, timing each
    call individually with `time.perf_counter()` (wall-clock, includes
    Python-level overhead - deliberately, since that overhead is real
    latency an inference request would also pay), and return p50/p95/mean
    in milliseconds plus the sample count `n`.

    Raises `ValueError` on an empty `aligned_crops` list - there is no
    meaningful latency distribution with zero samples, and silently
    returning zeros would look like "0ms latency" instead of "not
    measured".
    """
    if not aligned_crops:
        raise ValueError("measure_embedding_latency_ms: aligned_crops must be non-empty")

    timings_ms: list[float] = []
    for crop in aligned_crops:
        start = time.perf_counter()
        embedder.embed(crop)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        timings_ms.append(elapsed_ms)

    arr = np.asarray(timings_ms, dtype=np.float64)
    return {
        "latency_ms_p50": float(np.percentile(arr, 50)),
        "latency_ms_p95": float(np.percentile(arr, 95)),
        "latency_ms_mean": float(np.mean(arr)),
        "n": float(len(timings_ms)),
    }
