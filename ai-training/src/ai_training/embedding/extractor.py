"""Embedding extraction stub (TR-03).

Produces L2-normalized 512-d AdaFace embeddings per aligned face crop and
aggregates one template per pose bin (mean of normalized embeddings).
``torch`` is imported lazily - the module stays importable without the
``ml`` extra.
"""

from __future__ import annotations

from typing import Any


def _require_torch() -> Any:
    try:
        import torch
    except ImportError as exc:  # pragma: no cover - depends on extras
        raise RuntimeError(
            "Embedding extraction requires the 'ml' extra (uv sync --extra ml)."
        ) from exc
    return torch


def embed_faces(aligned_crops: list[bytes], model_version: str) -> list[list[float]]:
    """Embed aligned 112x112 crops with the pinned AdaFace model. TR-03."""
    _require_torch()
    raise NotImplementedError("Embedding extraction lands with TR-03.")
