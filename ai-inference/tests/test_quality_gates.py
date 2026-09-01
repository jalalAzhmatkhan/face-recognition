"""Unit tests for `ai_inference.pipeline.quality_gates` (EC-IN-02,
TSD-edge-cases.md D-3 C-1/C-3/C-4). Pure Python/numpy only -- no cv2/torch,
runs on base CI."""

from __future__ import annotations

import time

import numpy as np

from ai_inference.pipeline.quality_gates import (
    MIN_FACE_PX_DETECTION,
    MIN_FACE_PX_MATCHING,
    VOTING_WINDOW_MAX_FRAMES,
    VOTING_WINDOW_MIN_FRAMES,
    SizeGateResult,
    VotingWindowStats,
    evaluate_fiqa_gate,
    evaluate_size_gate,
)

# --- C-1: min-face-size gate --------------------------------------------


def test_size_gate_large_face_passes_both_tiers() -> None:
    result = evaluate_size_gate((120.0, 130.0))
    assert result == SizeGateResult(usable_for_detection=True, usable_for_matching=True)
    assert result.skipped is False


def test_size_gate_below_matching_floor_still_usable_for_detection() -> None:
    # 70px: clears the 64px detection floor, fails the 80px matching floor.
    result = evaluate_size_gate((70.0, 75.0))
    assert result.usable_for_detection is True
    assert result.usable_for_matching is False
    assert result.skipped is True


def test_size_gate_below_detection_floor_fails_both_tiers() -> None:
    # 50px: below the 64px detection floor entirely.
    result = evaluate_size_gate((50.0, 55.0))
    assert result.usable_for_detection is False
    assert result.usable_for_matching is False
    assert result.skipped is True


def test_size_gate_uses_shortest_side() -> None:
    # width=200 (plenty), height=50 (below detection floor) -- shortest
    # side must drive the decision, not the longer dimension.
    result = evaluate_size_gate((200.0, 50.0))
    assert result.usable_for_detection is False


def test_size_gate_exact_boundary_is_inclusive() -> None:
    result_detect = evaluate_size_gate((MIN_FACE_PX_DETECTION, MIN_FACE_PX_DETECTION))
    assert result_detect.usable_for_detection is True

    result_match = evaluate_size_gate((MIN_FACE_PX_MATCHING, MIN_FACE_PX_MATCHING))
    assert result_match.usable_for_matching is True


def test_size_gate_custom_thresholds_override_defaults() -> None:
    result = evaluate_size_gate(
        (90.0, 90.0), min_face_px_detection=100.0, min_face_px_matching=200.0
    )
    assert result.usable_for_detection is False
    assert result.usable_for_matching is False


# --- C-3: FIQA feature-norm gate -----------------------------------------


def test_fiqa_gate_passes_above_threshold() -> None:
    assert evaluate_fiqa_gate(20.0, min_feature_norm=15.0) is True


def test_fiqa_gate_fails_below_threshold() -> None:
    assert evaluate_fiqa_gate(5.0, min_feature_norm=15.0) is False


def test_fiqa_gate_exact_boundary_passes() -> None:
    assert evaluate_fiqa_gate(15.0, min_feature_norm=15.0) is True


def test_fiqa_gate_none_always_passes() -> None:
    # No feature-norm signal available (e.g. StubEmbedder backend) must
    # never be treated as "low quality" -- unmeasurable != positive finding.
    assert evaluate_fiqa_gate(None, min_feature_norm=15.0) is True
    assert evaluate_fiqa_gate(None, min_feature_norm=1000.0) is True


# --- C-4: explicit voting window bookkeeping ------------------------------


def test_voting_window_skip_rate_computed_correctly() -> None:
    stats = VotingWindowStats(frames_submitted=10, frames_voted=8, frames_skipped_quality_gate=2)
    assert stats.skip_rate == 0.2


def test_voting_window_skip_rate_zero_frames_is_zero_not_division_error() -> None:
    stats = VotingWindowStats(frames_submitted=0, frames_voted=0, frames_skipped_quality_gate=0)
    assert stats.skip_rate == 0.0


def test_voting_window_within_recommended_range() -> None:
    assert VotingWindowStats(3, 3, 0).within_recommended_window is True
    assert VotingWindowStats(5, 5, 0).within_recommended_window is True
    assert VotingWindowStats(2, 2, 0).within_recommended_window is False
    assert VotingWindowStats(6, 6, 0).within_recommended_window is False


def test_voting_window_constants_match_tsd_d3_c4() -> None:
    assert VOTING_WINDOW_MIN_FRAMES == 3
    assert VOTING_WINDOW_MAX_FRAMES == 5


# --- Overhead budget: gate components must stay comfortably <1ms/frame ---
# (task brief: "overhead <1ms/frame utk komponen gate (exclude FIQA yg
# sudah bagian dari embedding pipeline)" -- exercises evaluate_size_gate
# only, since evaluate_fiqa_gate is a single comparison and FIQA's real
# cost (the embed() forward pass itself) is out of scope for this budget.


def test_size_gate_overhead_budget() -> None:
    bboxes = [(float(60 + i % 40), float(60 + (i * 7) % 40)) for i in range(2000)]
    start = time.perf_counter()
    for bbox in bboxes:
        evaluate_size_gate(bbox)
    elapsed = time.perf_counter() - start
    per_frame_ms = (elapsed / len(bboxes)) * 1000.0
    assert per_frame_ms < 1.0, f"size gate overhead {per_frame_ms:.4f}ms/frame exceeds 1ms budget"


def test_fiqa_gate_overhead_budget() -> None:
    norms = np.linspace(0.0, 30.0, 2000)
    start = time.perf_counter()
    for norm in norms:
        evaluate_fiqa_gate(float(norm))
    elapsed = time.perf_counter() - start
    per_frame_ms = (elapsed / len(norms)) * 1000.0
    assert per_frame_ms < 1.0, f"FIQA gate overhead {per_frame_ms:.4f}ms/frame exceeds 1ms budget"
