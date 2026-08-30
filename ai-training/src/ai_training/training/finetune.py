"""Fine-tuning pipeline stub (TR-06).

One-time *domain* fine-tuning of the AdaFace backbone (not per-identity -
enrollment is gallery-based embedding matching, recommendations.md SS3).
Every run logs params/metrics/artifacts to MLflow and registers the model
as CANDIDATE; promotion is a human gate (FR-TRN-05).
``torch``/``mlflow`` are imported lazily inside the job.
"""

from __future__ import annotations

from ai_training.config import Settings


def run_finetune_job(settings: Settings, snapshot_id: str) -> str:
    """Run a fine-tune job on a dataset snapshot; returns the MLflow run id."""
    raise NotImplementedError("Fine-tuning lands with TR-06.")
