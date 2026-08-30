"""Evaluation metrics stub (TR-07).

Frozen benchmark (held-out identities + impostor set, versioned in S3).
Report order is fixed by project rule: Recall (primary) -> F1 -> Precision,
plus inference latency in ms. Gate: Recall >= 0.98 @ FAR <= 0.1% (ASM-07).
"""

from __future__ import annotations

from pydantic import BaseModel


class EvalReport(BaseModel):
    """Metric report in project priority order."""

    recall: float
    f1: float
    precision: float
    latency_ms_p95: float
    far: float
    model_version: str


def evaluate_candidate(model_version: str, benchmark_id: str) -> EvalReport:
    """Run the frozen benchmark against a candidate model. TR-07."""
    raise NotImplementedError("Evaluation harness lands with TR-07.")
