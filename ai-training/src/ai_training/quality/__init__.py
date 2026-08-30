"""Enrollment quality-check (QC) pipeline (TR-02, FR-ENR-06).

Sub-modules:
- `metrics`: pure-numpy blur/brightness/face-size quality metrics.
- `pose`: clock-position <-> (yaw, pitch) mapping + landmark-based pose
  estimation (ASM-03, corrected 2026-08-30 — head yaw/pitch only).
- `report`: Pydantic `QCReport`/`PositionResult` schema.
- `pipeline`: orchestrates video decode -> per-frame detection/pose/quality
  -> per-clock-position coverage -> PASS/REJECTED_QUALITY decision.
"""
