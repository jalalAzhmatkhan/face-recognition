"""Unit tests for the pure decision logic in `ai_inference.pipeline.recognize`
(IN-03; SPOOF_SUSPECTED voting added IN-04). No DB/torch/cv2 -- must pass on
base CI (no `ml` extra)."""

from ai_inference.pipeline.recognize import (
    FrameCandidate,
    RecognitionResult,
    decide_from_scores,
    frame_passes_threshold,
)

THRESHOLD = 0.5
MARGIN = 0.1
MIN_FRAMES = 2


def test_frame_passes_when_top1_clears_threshold_and_no_top2() -> None:
    candidate = FrameCandidate(top1_user_id="u1", top1_similarity=0.6, top2_similarity=None)
    assert frame_passes_threshold(candidate, threshold=THRESHOLD, margin=MARGIN) == ("u1", 0.6)


def test_frame_fails_when_top1_below_threshold() -> None:
    candidate = FrameCandidate(top1_user_id="u1", top1_similarity=0.49, top2_similarity=None)
    assert frame_passes_threshold(candidate, threshold=THRESHOLD, margin=MARGIN) is None


def test_frame_fails_when_margin_not_met() -> None:
    # top1=0.75, top2=0.625 -> margin=0.125 < required 0.1... use exact
    # binary fractions throughout to avoid float-precision false failures:
    # top1=0.6875, top2=0.625 -> margin=0.0625 < required 0.1
    candidate = FrameCandidate(top1_user_id="u1", top1_similarity=0.6875, top2_similarity=0.625)
    assert frame_passes_threshold(candidate, threshold=THRESHOLD, margin=MARGIN) is None


def test_frame_passes_when_margin_exactly_met() -> None:
    # top1=0.75, top2=0.5 -> margin=0.25 == required MARGIN_EXACT (inclusive)
    # 0.25 required chosen here (not module-level MARGIN) so the subtraction
    # (0.75 - 0.5 = 0.25) is exact in binary floating point.
    candidate = FrameCandidate(top1_user_id="u1", top1_similarity=0.75, top2_similarity=0.5)
    assert frame_passes_threshold(candidate, threshold=THRESHOLD, margin=0.25) == ("u1", 0.75)


def test_frame_with_no_candidate_never_passes() -> None:
    candidate = FrameCandidate(top1_user_id=None, top1_similarity=None, top2_similarity=None)
    assert frame_passes_threshold(candidate, threshold=THRESHOLD, margin=MARGIN) is None


def test_decide_grants_when_same_user_wins_min_frames() -> None:
    candidates = [
        FrameCandidate(top1_user_id="u1", top1_similarity=0.6),
        FrameCandidate(top1_user_id="u1", top1_similarity=0.7),
        FrameCandidate(top1_user_id=None, top1_similarity=None),  # no face detected
    ]
    result = decide_from_scores(
        candidates, threshold=THRESHOLD, margin=MARGIN, min_frames_for_grant=MIN_FRAMES
    )
    assert result == RecognitionResult(decision="GRANTED", user_id="u1", similarity=0.7)


def test_decide_unknown_when_no_user_reaches_min_frames() -> None:
    candidates = [
        FrameCandidate(top1_user_id="u1", top1_similarity=0.6),
        FrameCandidate(top1_user_id="u2", top1_similarity=0.55),
        FrameCandidate(top1_user_id=None, top1_similarity=None),
    ]
    result = decide_from_scores(
        candidates, threshold=THRESHOLD, margin=MARGIN, min_frames_for_grant=MIN_FRAMES
    )
    assert result == RecognitionResult(decision="UNKNOWN", user_id=None, similarity=0.0)


def test_decide_unknown_when_all_frames_below_threshold() -> None:
    candidates = [
        FrameCandidate(top1_user_id="u1", top1_similarity=0.2),
        FrameCandidate(top1_user_id="u1", top1_similarity=0.3),
        FrameCandidate(top1_user_id="u1", top1_similarity=0.1),
    ]
    result = decide_from_scores(
        candidates, threshold=THRESHOLD, margin=MARGIN, min_frames_for_grant=MIN_FRAMES
    )
    assert result == RecognitionResult(decision="UNKNOWN", user_id=None, similarity=0.0)


def test_decide_unknown_when_all_frames_have_no_face() -> None:
    candidates = [
        FrameCandidate(top1_user_id=None, top1_similarity=None),
        FrameCandidate(top1_user_id=None, top1_similarity=None),
    ]
    result = decide_from_scores(
        candidates, threshold=THRESHOLD, margin=MARGIN, min_frames_for_grant=MIN_FRAMES
    )
    assert result == RecognitionResult(decision="UNKNOWN", user_id=None, similarity=0.0)


def test_decide_ties_broken_by_higher_max_similarity() -> None:
    # u1 wins 2 frames (max 0.6), u2 wins 2 frames (max 0.9) -- same vote
    # count, u2 has the higher max similarity so u2 wins.
    candidates = [
        FrameCandidate(top1_user_id="u1", top1_similarity=0.55),
        FrameCandidate(top1_user_id="u1", top1_similarity=0.6),
        FrameCandidate(top1_user_id="u2", top1_similarity=0.9),
        FrameCandidate(top1_user_id="u2", top1_similarity=0.8),
    ]
    result = decide_from_scores(
        candidates, threshold=THRESHOLD, margin=MARGIN, min_frames_for_grant=MIN_FRAMES
    )
    assert result == RecognitionResult(decision="GRANTED", user_id="u2", similarity=0.9)


def test_decide_more_votes_beats_higher_single_similarity() -> None:
    # u1 wins 3 frames (max 0.55), u2 wins 2 frames (max 0.95) -- u1 has
    # more votes so u1 wins despite a lower max similarity.
    candidates = [
        FrameCandidate(top1_user_id="u1", top1_similarity=0.51),
        FrameCandidate(top1_user_id="u1", top1_similarity=0.52),
        FrameCandidate(top1_user_id="u1", top1_similarity=0.55),
        FrameCandidate(top1_user_id="u2", top1_similarity=0.95),
        FrameCandidate(top1_user_id="u2", top1_similarity=0.90),
    ]
    result = decide_from_scores(
        candidates, threshold=THRESHOLD, margin=MARGIN, min_frames_for_grant=MIN_FRAMES
    )
    assert result == RecognitionResult(decision="GRANTED", user_id="u1", similarity=0.55)


def test_decide_empty_candidate_list_is_unknown() -> None:
    result = decide_from_scores(
        [], threshold=THRESHOLD, margin=MARGIN, min_frames_for_grant=MIN_FRAMES
    )
    assert result == RecognitionResult(decision="UNKNOWN", user_id=None, similarity=0.0)


def test_decide_min_frames_for_grant_of_one_grants_on_single_pass() -> None:
    candidates = [FrameCandidate(top1_user_id="u1", top1_similarity=0.9)]
    result = decide_from_scores(
        candidates, threshold=THRESHOLD, margin=MARGIN, min_frames_for_grant=1
    )
    assert result == RecognitionResult(decision="GRANTED", user_id="u1", similarity=0.9)


# --- IN-04: SPOOF_SUSPECTED voting -------------------------------------


def test_decide_spoof_suspected_when_all_frames_flagged() -> None:
    candidates = [
        FrameCandidate(top1_user_id=None, top1_similarity=None, spoof_suspect=True),
        FrameCandidate(top1_user_id=None, top1_similarity=None, spoof_suspect=True),
    ]
    result = decide_from_scores(
        candidates, threshold=THRESHOLD, margin=MARGIN, min_frames_for_grant=MIN_FRAMES
    )
    assert result == RecognitionResult(decision="SPOOF_SUSPECTED", user_id=None, similarity=0.0)


def test_decide_spoof_suspected_wins_over_granted_user_from_other_frames() -> None:
    # 2 frames flagged spoof-suspect (reaches MIN_FRAMES) AND 2 OTHER frames
    # separately pass identity voting for u1 (also reaches MIN_FRAMES) --
    # SPOOF_SUSPECTED must win regardless, per the documented priority rule.
    candidates = [
        FrameCandidate(top1_user_id=None, top1_similarity=None, spoof_suspect=True),
        FrameCandidate(top1_user_id=None, top1_similarity=None, spoof_suspect=True),
        FrameCandidate(top1_user_id="u1", top1_similarity=0.9),
        FrameCandidate(top1_user_id="u1", top1_similarity=0.8),
    ]
    result = decide_from_scores(
        candidates, threshold=THRESHOLD, margin=MARGIN, min_frames_for_grant=MIN_FRAMES
    )
    assert result == RecognitionResult(decision="SPOOF_SUSPECTED", user_id=None, similarity=0.0)


def test_decide_not_spoof_suspected_when_below_min_frames() -> None:
    # Only 1 spoof-suspect frame, MIN_FRAMES=2 -- not enough to flag spoof;
    # falls through to normal identity voting (which also fails here, so
    # UNKNOWN) -- proves a single flagged frame alone can't tank the result.
    candidates = [
        FrameCandidate(top1_user_id=None, top1_similarity=None, spoof_suspect=True),
        FrameCandidate(top1_user_id="u1", top1_similarity=0.9),
    ]
    result = decide_from_scores(
        candidates, threshold=THRESHOLD, margin=MARGIN, min_frames_for_grant=MIN_FRAMES
    )
    assert result == RecognitionResult(decision="UNKNOWN", user_id=None, similarity=0.0)


def test_decide_no_spoof_frames_behaves_exactly_as_before() -> None:
    # Regression: identical to test_decide_grants_when_same_user_wins_min_frames
    # above but with spoof_suspect explicitly False everywhere -- confirms
    # the IN-04 addition changes nothing when there is no spoof signal.
    candidates = [
        FrameCandidate(top1_user_id="u1", top1_similarity=0.6, spoof_suspect=False),
        FrameCandidate(top1_user_id="u1", top1_similarity=0.7, spoof_suspect=False),
        FrameCandidate(top1_user_id=None, top1_similarity=None, spoof_suspect=False),
    ]
    result = decide_from_scores(
        candidates, threshold=THRESHOLD, margin=MARGIN, min_frames_for_grant=MIN_FRAMES
    )
    assert result == RecognitionResult(decision="GRANTED", user_id="u1", similarity=0.7)
