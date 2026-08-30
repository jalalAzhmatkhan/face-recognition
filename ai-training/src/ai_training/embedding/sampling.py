"""Best-frame-per-pose-bucket sampling (TR-03).

Deliberately generic over "anything with a `blur`/`passed` field" (rather
than importing `ai_training.quality.pipeline.FrameQuality` directly) so it
stays unit-testable with plain dataclasses/namedtuples and no `cv2`
dependency (see `tests/test_sampling.py`).
"""

from __future__ import annotations

from typing import Protocol


class _ScoredCandidate(Protocol):
    blur: float
    passed: bool


def select_best_frames[CandidateT: _ScoredCandidate](
    candidates: list[CandidateT], k: int = 1
) -> list[CandidateT]:
    """Pick up to `k` best candidates for one pose bucket, ranked by blur
    score (sharper = better; recommendations.md §4 step 5, "pilih K frame
    terbaik per bin").

    Prefers frames that passed QC; if none did (shouldn't normally happen —
    the caller only calls this for buckets `run_quality_check` marked as
    having at least one candidate — but a bucket can have candidates that
    all individually failed some OTHER position's stricter check), falls
    back to the full candidate pool rather than returning nothing.
    """
    passing = [c for c in candidates if c.passed]
    pool = passing or candidates
    return sorted(pool, key=lambda c: c.blur, reverse=True)[:k]
