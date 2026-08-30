"""QC report schema (TR-02, FR-ENR-06).

Stored verbatim (via `.model_dump(mode="json")`) into
`enrollment_sessions.qc_report` (jsonb) by the worker
(`ai_training.worker.tasks`).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PositionResult(BaseModel):
    """Pass/fail outcome for one of the 12 clock positions."""

    position: str  # "01".."12"
    passed: bool
    reasons: list[str] = Field(default_factory=list)
    best_score: float | None = None  # blur_score of the winning frame, if any


class QCReport(BaseModel):
    session_id: str
    overall: str  # "PASS" | "REJECTED_QUALITY"
    coverage_ratio: float
    positions: list[PositionResult]
    generated_at: datetime
