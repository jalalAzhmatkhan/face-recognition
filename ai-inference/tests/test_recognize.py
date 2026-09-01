"""Unit tests for the pure decision logic in `ai_inference.pipeline.recognize`
(IN-03; SPOOF_SUSPECTED voting added IN-04; IN-07's model-version-mismatch
guard, exercised with an empty frame list so no cv2/torch is touched). No
DB/torch/cv2 -- must pass on base CI (no `ml` extra)."""

from ai_inference.pipeline.recognize import (
    FrameCandidate,
    RecognitionResult,
    _determine_reject_stage,
    decide_from_scores,
    frame_passes_threshold,
    run_recognition,
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


# --- IN-07: model-version-mismatch fail-secure guard -------------------
# `run_recognition([], ...)` never reaches the frame loop (no frames to
# iterate), so this exercises the real orchestration function's guard logic
# with zero cv2/torch/DB dependency -- only a fake cursor/embedder.


class _FakeCursorWithProductionVersion:
    def __init__(self, production_version: str | None) -> None:
        self._production_version = production_version

    def execute(self, query: str, params: tuple = ()) -> None:
        pass

    def fetchone(self):
        return (self._production_version,) if self._production_version else None

    def fetchall(self):
        return []


class _FakeEmbedder:
    def __init__(self, model_version: str) -> None:
        self.model_version = model_version

    def embed(self, aligned_crop):  # pragma: no cover - unreachable with no frames
        raise AssertionError("embed() must not be called on a version mismatch")


def test_run_recognition_unknown_when_embedder_version_mismatches_production() -> None:
    from ai_inference.config import Settings

    settings = Settings()
    cursor = _FakeCursorWithProductionVersion("adaface-ir101-webface12m-v2")
    embedder = _FakeEmbedder("adaface-ir101-webface12m-v1")

    result, model_version, liveness_scores = run_recognition(
        [], settings, embedder=embedder, cursor=cursor
    )
    assert result == RecognitionResult(decision="UNKNOWN", user_id=None, similarity=0.0)
    # Reports the ACTUAL production version (even though unused) so an
    # operator can see "production moved on, this replica hasn't" -- see
    # ai_inference.model_switch module docstring.
    assert model_version == "adaface-ir101-webface12m-v2"
    assert liveness_scores == []


def test_run_recognition_unknown_when_no_production_model_at_all() -> None:
    """Regression: pre-IN-07 fail-secure path (no PRODUCTION row) must be
    unaffected by the new mismatch guard."""
    from ai_inference.config import Settings

    settings = Settings()
    cursor = _FakeCursorWithProductionVersion(None)
    embedder = _FakeEmbedder("adaface-ir101-webface12m-v1")

    result, model_version, liveness_scores = run_recognition(
        [], settings, embedder=embedder, cursor=cursor
    )
    assert result == RecognitionResult(decision="UNKNOWN", user_id=None, similarity=0.0)
    assert model_version == ""
    assert liveness_scores == []


# NOTE: a "versions match, guard passes through" test is deliberately NOT
# included here -- even with an empty frame list, `run_recognition` past
# the guard unconditionally imports `ai_training.embedding.alignment` /
# `ai_training.quality.pose` (needs the `ml` extra), so that path is left to
# this project's established live-verification convention instead (see
# module docstring), same as the rest of `run_recognition`'s orchestration.


# --- EC-IN-01: reject_stage determination (TSD-edge-cases.md D-1) -------


def test_reject_stage_none_when_granted() -> None:
    result = RecognitionResult(decision="GRANTED", user_id="u1", similarity=0.9)
    assert _determine_reject_stage(result, [FrameCandidate("u1", 0.9)]) is None


def test_reject_stage_liveness_when_spoof_suspected() -> None:
    result = RecognitionResult(decision="SPOOF_SUSPECTED", user_id=None, similarity=0.0)
    candidates = [
        FrameCandidate(top1_user_id=None, top1_similarity=None, spoof_suspect=True),
        FrameCandidate(top1_user_id=None, top1_similarity=None, spoof_suspect=True),
    ]
    assert _determine_reject_stage(result, candidates) == "liveness"


def test_reject_stage_detection_when_no_candidates_at_all() -> None:
    # UNKNOWN with an empty candidate list: every submitted frame either
    # failed to decode or had no detected face -- never reached liveness.
    result = RecognitionResult(decision="UNKNOWN", user_id=None, similarity=0.0)
    assert _determine_reject_stage(result, []) == "detection"


def test_reject_stage_liveness_when_unknown_but_some_frames_spoof_suspect() -> None:
    # Below min_frames_for_grant for an outright SPOOF_SUSPECTED verdict,
    # but a liveness concern was raised on at least one frame -- prioritized
    # over "threshold" per _determine_reject_stage's documented rationale.
    result = RecognitionResult(decision="UNKNOWN", user_id=None, similarity=0.0)
    candidates = [
        FrameCandidate(top1_user_id=None, top1_similarity=None, spoof_suspect=True),
        FrameCandidate(top1_user_id="u1", top1_similarity=0.9),
    ]
    assert _determine_reject_stage(result, candidates) == "liveness"


def test_reject_stage_threshold_when_unknown_with_only_non_spoof_candidates() -> None:
    result = RecognitionResult(decision="UNKNOWN", user_id=None, similarity=0.0)
    candidates = [
        FrameCandidate(top1_user_id="u1", top1_similarity=0.2),
        FrameCandidate(top1_user_id="u2", top1_similarity=0.25),
    ]
    assert _determine_reject_stage(result, candidates) == "threshold"


def test_recognition_result_defaults_condition_flags_and_reject_stage() -> None:
    # decide_from_scores itself never sets these (added later by
    # run_recognition via dataclasses.replace) -- confirm the dataclass
    # defaults keep every EXISTING equality-based test in this file valid.
    result = decide_from_scores(
        [], threshold=THRESHOLD, margin=MARGIN, min_frames_for_grant=MIN_FRAMES
    )
    assert result.condition_flags == {}
    assert result.reject_stage is None


# --- EC-IN-02: quality gates (C-1 size, C-3 FIQA) wired into
# `run_recognition`, log-only-by-default (TSD-edge-cases.md D-3) ---------
#
# `run_recognition`'s full body is normally left to this project's
# established "live verification" convention (needs cv2 + torch + a real
# DB, see module docstring) -- but `_decode_frame_bgr`/`detect_face_and_
# landmarks`/`align_face` are all monkeypatchable seams (the latter two are
# `from module import name` LOCAL imports executed fresh on every
# `run_recognition` call, so patching the *source* module's attribute
# before calling takes effect), which lets these specific gate-wiring
# behaviors be exercised without any of those heavy dependencies.


class _FiqaFakeCursor:
    def __init__(self, production_version: str) -> None:
        self._production_version = production_version

    def execute(self, query: str, params: tuple = ()) -> None:
        pass

    def fetchone(self):
        return (self._production_version,)

    def fetchall(self):
        return []


class _FiqaFakeEmbedder:
    """Exposes `embed_with_quality` (like `AdaFaceEmbedder`) with a
    controllable, fixed `feature_norm`."""

    def __init__(self, model_version: str, feature_norm: float | None) -> None:
        self.model_version = model_version
        self._feature_norm = feature_norm

    def embed(self, aligned_crop):  # pragma: no cover - embed_with_quality always used instead
        raise AssertionError("run_recognition must call embed_with_quality, not embed")

    def embed_with_quality(self, aligned_crop):
        return [0.1] * 512, self._feature_norm


class _MustNotBeCalledLivenessDetector:
    def score(self, frame_bgr, bbox_xy, bbox_wh):
        raise AssertionError(
            "liveness_detector.score must not be called for a frame skipped "
            "at the C-1 detection-floor gate"
        )


class _AlwaysLiveLivenessDetector:
    def score(self, frame_bgr, bbox_xy, bbox_wh):
        return 1.0  # comfortably above any default liveness_threshold


class _FakeFaceDetection:
    """Duck-typed stand-in for `ai_training.quality.pose.FaceDetection` --
    only the attributes `run_recognition` actually reads. Avoids a hard
    dependency on the real `ai_training` package (installed only under
    ai-inference's own `ml` extra, see that package's pyproject.toml
    comment) so these gate-WIRING tests stay runnable on base CI, same as
    every other test in this file."""

    def __init__(self, bbox_wh: tuple[float, float]) -> None:
        self.bbox_wh = bbox_wh
        self.bbox_xy = (0.0, 0.0)
        self.left_eye = (40.0, 40.0)
        self.right_eye = (60.0, 40.0)
        self.left_mouth = (40.0, 70.0)
        self.right_mouth = (60.0, 70.0)

    def alignment_landmarks_5pt(self):
        return None


def _patch_common_seams(monkeypatch, *, bbox_wh: tuple[float, float]) -> None:
    """Injects FAKE `ai_training.quality.pose`/`ai_training.embedding.
    alignment` modules directly into `sys.modules` (removed automatically
    by `monkeypatch` on teardown) rather than patching attributes on the
    real modules -- the real `ai_training` package needs ai-inference's
    `ml` extra (torch/opencv/mediapipe) which base CI does not install, so
    a plain `import ai_training...` here would itself fail. `sys.modules`
    injection makes `run_recognition`'s own `from ai_training.quality.pose
    import detect_face_and_landmarks` (a fresh import executed on every
    call) resolve to these fakes instead, without ever needing the real
    package on disk. Shared by every gate-wiring test below."""
    import sys
    import types

    import numpy as np

    from ai_inference.pipeline import recognize as recognize_module

    fake_frame = np.zeros((100, 100, 3), dtype=np.uint8)
    monkeypatch.setattr(recognize_module, "_decode_frame_bgr", lambda frame_b64: fake_frame)

    fake_detection = _FakeFaceDetection(bbox_wh)

    ai_training_pkg = types.ModuleType("ai_training")
    quality_pkg = types.ModuleType("ai_training.quality")
    pose_module = types.ModuleType("ai_training.quality.pose")
    pose_module.detect_face_and_landmarks = lambda frame_bgr: fake_detection
    embedding_pkg = types.ModuleType("ai_training.embedding")
    alignment_module = types.ModuleType("ai_training.embedding.alignment")
    alignment_module.align_face = lambda frame_bgr, landmarks: fake_frame

    for name, module in (
        ("ai_training", ai_training_pkg),
        ("ai_training.quality", quality_pkg),
        ("ai_training.quality.pose", pose_module),
        ("ai_training.embedding", embedding_pkg),
        ("ai_training.embedding.alignment", alignment_module),
    ):
        monkeypatch.setitem(sys.modules, name, module)


def _patch_gallery_returns_one_match(monkeypatch, *, user_id: str, similarity: float) -> None:
    from ai_inference import gallery as gallery_module

    monkeypatch.setattr(
        gallery_module, "search_top_k", lambda cursor, **kwargs: [(user_id, similarity)]
    )


def _run_two_frame_recognition(monkeypatch, settings, *, embedder, liveness_detector):
    cursor = _FiqaFakeCursor(embedder.model_version)
    return run_recognition(
        ["frame_a", "frame_b"],
        settings,
        embedder=embedder,
        cursor=cursor,
        liveness_detector=liveness_detector,
    )


def test_fiqa_gate_log_only_never_changes_decision(monkeypatch) -> None:
    """`Settings.quality_gate_enforcing` default (False): a low FIQA
    feature-norm on every frame must NOT change the final decision at
    all -- the whole point of shipping log-only."""
    from ai_inference.config import Settings

    settings = Settings(min_frames_for_grant=1)
    assert settings.quality_gate_enforcing is False  # default confirmed

    _patch_common_seams(monkeypatch, bbox_wh=(120.0, 120.0))  # clears both C-1 tiers
    _patch_gallery_returns_one_match(monkeypatch, user_id="u1", similarity=0.9)
    embedder = _FiqaFakeEmbedder(
        "adaface-ir101-webface12m",
        feature_norm=1.0,  # far below any sane FIQA threshold
    )

    result, _model_version, _liveness_scores = _run_two_frame_recognition(
        monkeypatch, settings, embedder=embedder, liveness_detector=_AlwaysLiveLivenessDetector()
    )
    assert result.decision == "GRANTED"
    assert result.user_id == "u1"
    # Still logged, even though it changed nothing about the decision.
    assert result.condition_flags["skipped_quality_gate"] is True


def test_fiqa_gate_enforcing_excludes_low_quality_frames_from_voting(monkeypatch) -> None:
    """Same scenario as above, `quality_gate_enforcing=True`: now the low
    feature-norm frames are excluded from the vote entirely -- no
    candidates reach `decide_from_scores`, so the decision flips to
    UNKNOWN. This is the one explicit enforcing-mode behavior-change test
    the task brief calls for."""
    from ai_inference.config import Settings

    settings = Settings(min_frames_for_grant=1, quality_gate_enforcing=True)

    _patch_common_seams(monkeypatch, bbox_wh=(120.0, 120.0))
    _patch_gallery_returns_one_match(monkeypatch, user_id="u1", similarity=0.9)
    embedder = _FiqaFakeEmbedder("adaface-ir101-webface12m", feature_norm=1.0)

    result, _model_version, _liveness_scores = _run_two_frame_recognition(
        monkeypatch, settings, embedder=embedder, liveness_detector=_AlwaysLiveLivenessDetector()
    )
    assert result.decision == "UNKNOWN"
    assert result.user_id is None
    assert result.condition_flags["skipped_quality_gate"] is True
    # Not a reject -- still "detection" (no candidates at all), never the
    # nonexistent "quality_gate" reject_stage value (see
    # `_determine_reject_stage`'s docstring).
    assert result.reject_stage == "detection"


def test_size_gate_log_only_still_reaches_gallery_search(monkeypatch) -> None:
    """A too-small-for-detection bbox (<64px), enforcing OFF: must behave
    exactly as it did before EC-IN-02 -- liveness AND gallery search both
    still run for this frame."""
    from ai_inference.config import Settings

    settings = Settings(min_frames_for_grant=1)

    _patch_common_seams(monkeypatch, bbox_wh=(50.0, 50.0))  # below the 64px detection floor
    _patch_gallery_returns_one_match(monkeypatch, user_id="u1", similarity=0.9)
    embedder = _FiqaFakeEmbedder("adaface-ir101-webface12m", feature_norm=None)

    result, _model_version, _liveness_scores = _run_two_frame_recognition(
        monkeypatch, settings, embedder=embedder, liveness_detector=_AlwaysLiveLivenessDetector()
    )
    assert result.decision == "GRANTED"
    assert result.condition_flags["skipped_quality_gate"] is True


def test_size_gate_enforcing_skips_before_liveness_for_tiny_faces(monkeypatch) -> None:
    """Enforcing ON, bbox below the 64px detection floor: the frame must be
    skipped BEFORE liveness is ever scored (proven by a liveness detector
    that raises if called) -- no candidate, no reject, decision UNKNOWN."""
    from ai_inference.config import Settings

    settings = Settings(min_frames_for_grant=1, quality_gate_enforcing=True)

    _patch_common_seams(monkeypatch, bbox_wh=(50.0, 50.0))
    _patch_gallery_returns_one_match(monkeypatch, user_id="u1", similarity=0.9)
    embedder = _FiqaFakeEmbedder("adaface-ir101-webface12m", feature_norm=None)

    result, _model_version, liveness_scores = _run_two_frame_recognition(
        monkeypatch,
        settings,
        embedder=embedder,
        liveness_detector=_MustNotBeCalledLivenessDetector(),
    )
    assert result.decision == "UNKNOWN"
    assert liveness_scores == []
    assert result.condition_flags["skipped_quality_gate"] is True


def test_size_gate_enforcing_allows_liveness_but_skips_matching_in_middle_band(monkeypatch) -> None:
    """A bbox in the 64-80px band (clears detection, fails matching),
    enforcing ON: liveness still scores this frame (contributes no spoof
    vote here since it's live), but embed/search must be skipped -- proven
    by an embedder that raises if its `embed_with_quality` is called."""
    from ai_inference.config import Settings

    class _MustNotEmbed(_FiqaFakeEmbedder):
        def embed_with_quality(self, aligned_crop):
            raise AssertionError(
                "embed_with_quality must not be called for a frame skipped "
                "at the C-1 matching-floor gate"
            )

    settings = Settings(min_frames_for_grant=1, quality_gate_enforcing=True)

    _patch_common_seams(monkeypatch, bbox_wh=(70.0, 70.0))  # 64px <= shortest < 80px
    _patch_gallery_returns_one_match(monkeypatch, user_id="u1", similarity=0.9)
    embedder = _MustNotEmbed("adaface-ir101-webface12m", feature_norm=None)

    result, _model_version, liveness_scores = _run_two_frame_recognition(
        monkeypatch, settings, embedder=embedder, liveness_detector=_AlwaysLiveLivenessDetector()
    )
    assert result.decision == "UNKNOWN"
    assert liveness_scores == [1.0, 1.0]  # liveness DID run for both frames
    assert result.condition_flags["skipped_quality_gate"] is True


def test_size_gate_middle_band_log_only_reaches_matching_normally(monkeypatch) -> None:
    """Same 64-80px band, enforcing OFF: matching must proceed exactly as
    it did before this task (no behavior change out of the box)."""
    from ai_inference.config import Settings

    settings = Settings(min_frames_for_grant=1)

    _patch_common_seams(monkeypatch, bbox_wh=(70.0, 70.0))
    _patch_gallery_returns_one_match(monkeypatch, user_id="u1", similarity=0.9)
    embedder = _FiqaFakeEmbedder("adaface-ir101-webface12m", feature_norm=None)

    result, _model_version, _liveness_scores = _run_two_frame_recognition(
        monkeypatch, settings, embedder=embedder, liveness_detector=_AlwaysLiveLivenessDetector()
    )
    assert result.decision == "GRANTED"


def test_quality_gate_passing_frames_never_flag_skipped_quality_gate(monkeypatch) -> None:
    """Regression/sanity: a request where every frame comfortably clears
    every gate must report `skipped_quality_gate=False`, regardless of
    `quality_gate_enforcing` (nothing to enforce)."""
    from ai_inference.config import Settings

    for enforcing in (False, True):
        settings = Settings(min_frames_for_grant=1, quality_gate_enforcing=enforcing)
        _patch_common_seams(monkeypatch, bbox_wh=(120.0, 120.0))
        _patch_gallery_returns_one_match(monkeypatch, user_id="u1", similarity=0.9)
        embedder = _FiqaFakeEmbedder("adaface-ir101-webface12m", feature_norm=50.0)

        result, _model_version, _liveness_scores = _run_two_frame_recognition(
            monkeypatch,
            settings,
            embedder=embedder,
            liveness_detector=_AlwaysLiveLivenessDetector(),
        )
        assert result.decision == "GRANTED"
        assert result.condition_flags["skipped_quality_gate"] is False


# --- EC-IN-04: dual-mode (normal/masked) threshold + masked-template
# gallery filter (TSD-edge-cases.md D-4.1/D-4.2, OQ-3/OQ-6) --------------


def _patch_condition_flags_masked(monkeypatch, masked: bool) -> None:
    """Forces every frame's `masked` condition flag to a known value,
    decoupled from `compute_condition_flags`'s real heuristic (which -- as
    it happens -- always flags the all-zero `fake_frame` used by
    `_patch_common_seams` as masked/dark/blurry/sunglasses; patching this
    explicitly keeps these EC-IN-04 tests' intent legible/robust instead of
    relying on that heuristic accident)."""
    from ai_inference.pipeline import condition_flags as condition_flags_module

    monkeypatch.setattr(
        condition_flags_module,
        "compute_condition_flags",
        lambda frame_bgr, **kwargs: {
            "dark": False,
            "blurry": False,
            "low_res": False,
            "masked": masked,
            "sunglasses": False,
        },
    )


def _patch_gallery_config_lookups(monkeypatch, *, device_class=None, override=None) -> None:
    """Stubs the two EC-IN-04 DB reads `run_recognition` performs ONLY when
    `dual_mode_threshold_enabled` (device_class lookup + recognition_configs
    override) -- isolates these gate-WIRING tests from needing a real
    `recognition_configs`-serving fake cursor (already covered directly by
    `tests/test_threshold_resolution.py` and `tests/test_gallery.py`)."""
    from ai_inference import gallery as gallery_module

    monkeypatch.setattr(gallery_module, "get_device_class", lambda cursor, device_id: device_class)
    monkeypatch.setattr(
        gallery_module,
        "get_recognition_config_override",
        lambda cursor, *, mode, device_class: override,
    )


def test_dual_mode_disabled_search_top_k_called_without_masked_kwarg(monkeypatch) -> None:
    """Regression: flag OFF (default) -- even a `masked`-flagged frame must
    take the exact pre-EC-IN-04 `search_top_k` call shape (no `masked`
    kwarg at all) and the exact pre-EC-IN-04 threshold."""
    from ai_inference.config import Settings

    settings = Settings(min_frames_for_grant=1, dual_mode_threshold_enabled=False)
    _patch_common_seams(monkeypatch, bbox_wh=(120.0, 120.0))
    _patch_condition_flags_masked(monkeypatch, masked=True)

    from ai_inference import gallery as gallery_module

    calls: list[dict] = []

    def fake_search(cursor, **kwargs):
        calls.append(kwargs)
        return [("u1", 0.9)]

    monkeypatch.setattr(gallery_module, "search_top_k", fake_search)

    embedder = _FiqaFakeEmbedder("adaface-ir101-webface12m", feature_norm=50.0)
    result, _model_version, _liveness_scores = _run_two_frame_recognition(
        monkeypatch, settings, embedder=embedder, liveness_detector=_AlwaysLiveLivenessDetector()
    )
    assert result.decision == "GRANTED"
    assert all("masked" not in c for c in calls)
    assert result.condition_flags["low_confidence_masked"] is False


def test_dual_mode_enabled_masked_probe_uses_masked_filtered_gallery_first(monkeypatch) -> None:
    from ai_inference.config import Settings

    settings = Settings(
        min_frames_for_grant=1,
        dual_mode_threshold_enabled=True,
        similarity_threshold_masked=0.3,
        similarity_threshold=0.9,  # deliberately too strict to matter here
    )
    _patch_common_seams(monkeypatch, bbox_wh=(120.0, 120.0))
    _patch_condition_flags_masked(monkeypatch, masked=True)
    _patch_gallery_config_lookups(monkeypatch)

    from ai_inference import gallery as gallery_module

    calls: list[bool | None] = []

    def fake_search(cursor, **kwargs):
        calls.append(kwargs.get("masked"))
        return [("u1", 0.5)]  # clears tau_masked (0.3), would fail tau_normal (0.9)

    monkeypatch.setattr(gallery_module, "search_top_k", fake_search)

    embedder = _FiqaFakeEmbedder("adaface-ir101-webface12m", feature_norm=50.0)
    result, _model_version, _liveness_scores = _run_two_frame_recognition(
        monkeypatch, settings, embedder=embedder, liveness_detector=_AlwaysLiveLivenessDetector()
    )
    assert calls == [True, True]  # both frames hit the masked-filtered gallery, no fallback needed
    assert result.decision == "GRANTED"
    assert result.user_id == "u1"
    assert result.condition_flags["low_confidence_masked"] is False


def test_dual_mode_enabled_masked_probe_falls_back_when_gallery_has_no_masked_templates(
    monkeypatch,
) -> None:
    """OQ-3: the masked-filtered gallery is entirely empty for this
    model_version (no synthetic_masked templates backfilled yet) -- falls
    back to the unmasked-template gallery, STILL under tau_masked (not
    tau_normal, not a third threshold), and flags `low_confidence_masked`."""
    from ai_inference.config import Settings

    settings = Settings(
        min_frames_for_grant=1,
        dual_mode_threshold_enabled=True,
        similarity_threshold_masked=0.3,
        similarity_threshold=0.9,  # if tau_normal were used instead, this would DENY
    )
    _patch_common_seams(monkeypatch, bbox_wh=(120.0, 120.0))
    _patch_condition_flags_masked(monkeypatch, masked=True)
    _patch_gallery_config_lookups(monkeypatch)

    from ai_inference import gallery as gallery_module

    calls: list[bool | None] = []

    def fake_search(cursor, **kwargs):
        calls.append(kwargs.get("masked"))
        if kwargs.get("masked") is True:
            return []  # no masked=true templates at all
        return [("u1", 0.5)]  # unmasked template, clears tau_masked (0.3)

    monkeypatch.setattr(gallery_module, "search_top_k", fake_search)

    embedder = _FiqaFakeEmbedder("adaface-ir101-webface12m", feature_norm=50.0)
    result, _model_version, _liveness_scores = _run_two_frame_recognition(
        monkeypatch, settings, embedder=embedder, liveness_detector=_AlwaysLiveLivenessDetector()
    )
    assert calls == [True, False, True, False]  # each of the 2 frames: masked miss, then fallback
    assert result.decision == "GRANTED"
    assert result.user_id == "u1"
    assert result.condition_flags["low_confidence_masked"] is True


def test_dual_mode_enabled_normal_probe_takes_unfiltered_gallery_call(monkeypatch) -> None:
    """A probe never flagged `masked`, flag ON: gallery call shape stays
    exactly the pre-EC-IN-04 unfiltered query -- only which Settings fields
    feed the threshold changes (still `similarity_threshold`/
    `margin_threshold`/`min_frames_for_grant`, resolved as the "normal"
    mode's artefact default, no override configured here)."""
    from ai_inference.config import Settings

    settings = Settings(min_frames_for_grant=1, dual_mode_threshold_enabled=True)
    _patch_common_seams(monkeypatch, bbox_wh=(120.0, 120.0))
    _patch_condition_flags_masked(monkeypatch, masked=False)
    _patch_gallery_config_lookups(monkeypatch)

    from ai_inference import gallery as gallery_module

    calls: list[dict] = []

    def fake_search(cursor, **kwargs):
        calls.append(kwargs)
        return [("u1", 0.9)]

    monkeypatch.setattr(gallery_module, "search_top_k", fake_search)

    embedder = _FiqaFakeEmbedder("adaface-ir101-webface12m", feature_norm=50.0)
    result, _model_version, _liveness_scores = _run_two_frame_recognition(
        monkeypatch, settings, embedder=embedder, liveness_detector=_AlwaysLiveLivenessDetector()
    )
    assert all("masked" not in c for c in calls)
    assert result.decision == "GRANTED"
    assert result.condition_flags["low_confidence_masked"] is False


def test_dual_mode_enabled_device_class_override_used_for_threshold(monkeypatch) -> None:
    """`recognition_configs` DEVICE_CLASS override on `similarity_threshold`
    is applied for a normal-mode probe when the flag is on (layer 2 of the
    OQ-6 resolution) -- overriding it to something so strict the otherwise-
    GRANTED similarity now fails."""
    from ai_inference.config import Settings

    settings = Settings(
        min_frames_for_grant=1, dual_mode_threshold_enabled=True, similarity_threshold=0.35
    )
    _patch_common_seams(monkeypatch, bbox_wh=(120.0, 120.0))
    _patch_condition_flags_masked(monkeypatch, masked=False)
    _patch_gallery_config_lookups(
        monkeypatch,
        device_class="door_entry",
        override={
            "similarity_threshold": 0.99,
            "margin": None,
            "liveness_threshold": None,
            "min_frames": None,
        },
    )

    from ai_inference import gallery as gallery_module

    monkeypatch.setattr(
        gallery_module, "search_top_k", lambda cursor, **kwargs: [("u1", 0.5)]
    )

    embedder = _FiqaFakeEmbedder("adaface-ir101-webface12m", feature_norm=50.0)
    result, _model_version, _liveness_scores = run_recognition(
        ["frame_a", "frame_b"],
        settings,
        embedder=embedder,
        cursor=_FiqaFakeCursor(embedder.model_version),
        liveness_detector=_AlwaysLiveLivenessDetector(),
        device_id="device-1",
    )
    # 0.5 clears the DEFAULT 0.35 but not the DEVICE_CLASS override's 0.99.
    assert result.decision == "UNKNOWN"


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
