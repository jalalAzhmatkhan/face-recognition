"""Embedding latency measurement (TR-07) - runs against `StubEmbedder`, no
`ml` extra needed (pure `time`/`numpy` orchestration)."""

from __future__ import annotations

import numpy as np
import pytest

from ai_training.embedding.embedder import StubEmbedder
from ai_training.evaluation.latency import measure_embedding_latency_ms


def test_measure_embedding_latency_ms_returns_percentiles_and_count() -> None:
    embedder = StubEmbedder()
    crops = [np.full((112, 112, 3), i, dtype=np.uint8) for i in range(5)]

    result = measure_embedding_latency_ms(embedder, crops)

    assert result["n"] == 5.0
    assert result["latency_ms_p50"] >= 0.0
    assert result["latency_ms_p95"] >= result["latency_ms_p50"]
    assert result["latency_ms_mean"] >= 0.0


def test_measure_embedding_latency_ms_rejects_empty_crops() -> None:
    embedder = StubEmbedder()
    with pytest.raises(ValueError, match="non-empty"):
        measure_embedding_latency_ms(embedder, [])
