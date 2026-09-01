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
    # EC-BE-02 (TSD-edge-cases.md D-4.1/D-10): additive, optional counters.
    # `enrollment_sessions.qc_report` is an untyped jsonb column, so these
    # don't need a migration -- they're just new optional keys in the
    # dict this model serializes to. `None` (not populated) means "the QC
    # worker run that produced this report predates these counters" or
    # "this session's variant/masked-template pipeline hasn't run yet",
    # never an error. `variants_captured`: which `MediaVariant` values
    # (A-1/A-3, gelombang 3) were captured for this session, if any.
    # `synthetic_templates_generated`: count of `synthetic_masked`
    # templates the A-4/D-4.5 pipeline produced from this session's video,
    # if that pipeline has run.
    variants_captured: list[str] | None = None
    synthetic_templates_generated: int | None = None
