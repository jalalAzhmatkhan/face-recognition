"""C-1/C-3/C-4 per-frame quality gates (EC-IN-02, TSD-edge-cases.md D-3).

Builds ON TOP of EC-IN-01's ``condition_flags`` module (``dark``/``blurry``/
``low_res``/``masked``/``sunglasses`` heuristics) rather than duplicating it:
this module answers a DIFFERENT question -- given those (and the AdaFace
embedding's own free-byproduct feature-norm), should THIS frame be SKIPPED
before it reaches liveness/embedding/voting? "Skipped" is a distinct outcome
from "rejected" everywhere in this module and its caller
(``ai_inference.pipeline.recognize.run_recognition``): a skipped frame
simply does not contribute a vote (TSD D-3 C-4) -- it never counts against
the subject the way a liveness/threshold rejection would, and it is NEVER
folded into ``reject_stage`` (see that module's docstring for why
``"quality_gate"`` is deliberately still not one of that field's values).

**SHIP LOG-ONLY (EC-IN-02 task brief)**: every function here is a pure,
side-effect-free predicate -- it always runs and its result is always
logged/counted, regardless of ``Settings.quality_gate_enforcing``. Only the
CALLER (``run_recognition``) decides whether a gate's outcome is allowed to
change actual pipeline behaviour (skip a frame for real) versus being
recorded for later analysis while every frame still flows through the
pipeline exactly as it did before this task landed. This is what makes "flag
OFF -> zero behavior change" possible to guarantee and test.

Threshold calibration status: every numeric threshold below is a documented
placeholder, same convention as ``ai_inference.pipeline.condition_flags`` --
final values are meant to come from this gate's own logged output (TSD D-3
C-1's explicit enforce criterion: legitimate-frame skip rate < 1-2% over
1-2 weeks, per ``device_class``), not from this module.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai_inference.pipeline.condition_flags import LOW_RES_MIN_PX

# --- C-1: cheap min-face-size gate (TSD D-3, REC 10.1) ---------------------
# Two-tier, per the task brief: a face smaller than this can't be trusted
# for ANYTHING downstream of detection (too little signal, period) -- this
# is STRICTER than (and independent of) EC-IN-01's existing `low_res` flag
# (`condition_flags.LOW_RES_MIN_PX == 80.0`, which this module reuses
# verbatim as the MATCHING-stage floor below, rather than duplicating the
# constant).
MIN_FACE_PX_DETECTION = 64.0
MIN_FACE_PX_MATCHING = LOW_RES_MIN_PX


@dataclass(frozen=True)
class SizeGateResult:
    """C-1 min-size gate outcome for one frame's detected bbox.

    - ``usable_for_detection=False``: bbox shortest side < 64px -- too small
      to trust for ANYTHING past detection (liveness/embedding/matching all
      skipped when enforcing).
    - ``usable_for_matching=False`` (while ``usable_for_detection=True``):
      bbox clears the 64px detection floor but not the 80px matching floor
      -- fine for liveness/spoof voting, too small to trust for identity
      matching (REC 10.1), so only the embed+search step is skipped when
      enforcing.
    """

    usable_for_detection: bool
    usable_for_matching: bool

    @property
    def skipped(self) -> bool:
        """True if this frame fails EITHER tier (log-only signal -- does
        NOT by itself mean the frame was actually dropped; see module
        docstring)."""
        return not self.usable_for_detection or not self.usable_for_matching


def evaluate_size_gate(
    bbox_wh: tuple[float, float],
    *,
    min_face_px_detection: float = MIN_FACE_PX_DETECTION,
    min_face_px_matching: float = MIN_FACE_PX_MATCHING,
) -> SizeGateResult:
    """Pure, <1us: a single `min()` + two comparisons. `bbox_wh` is the same
    `(width, height)` tuple `condition_flags.compute_condition_flags` and
    `ai_training.quality.pose.FaceDetection.bbox_wh` already use."""
    shortest_side = min(bbox_wh)
    usable_for_detection = shortest_side >= min_face_px_detection
    usable_for_matching = usable_for_detection and shortest_side >= min_face_px_matching
    return SizeGateResult(
        usable_for_detection=usable_for_detection,
        usable_for_matching=usable_for_matching,
    )


# --- C-3: FIQA gate -- AdaFace feature-norm (TSD D-3, REC S7) --------------
# AdaFace's own premise (Kim et al. 2022, "AdaFace: Quality Adaptive Margin
# for Face Recognition") is that the embedding's pre-L2-normalization norm
# correlates with input image quality -- it is a FREE byproduct of the same
# embed() forward pass (see
# `ai_training.embedding.embedder.EmbedderInterface.embed_with_quality`),
# never a second model call. Placeholder threshold, same "pending
# calibration from this gate's own logged histogram" status as every other
# threshold in this module.
FIQA_MIN_FEATURE_NORM = 15.0


def evaluate_fiqa_gate(
    feature_norm: float | None, *, min_feature_norm: float = FIQA_MIN_FEATURE_NORM
) -> bool:
    """True = frame passes the FIQA gate (usable pre-vote), False = skip.

    `feature_norm=None` (the embedder backend doesn't expose one -- e.g.
    `StubEmbedder`, the default in tests/CI/dev) ALWAYS passes: an
    unmeasurable quality signal must never be treated as a positive "low
    quality" finding, the same "can't measure it -> don't flag it" rule
    `condition_flags`'s degenerate-bbox handling already follows.
    """
    if feature_norm is None:
        return True
    return feature_norm >= min_feature_norm


# --- C-4: explicit 3-5 frame voting window (TSD D-3) -----------------------
# `ai_inference.config.Settings.min_frames_for_grant` already implements the
# CORE voting rule (a user must win the per-frame check in at least this
# many frames) -- this section only adds the explicit window-size bookkeeping
# the task brief calls for: whether a request's frame count actually falls
# in the design's recommended 3-5 frame range, and how many of those frames
# were skipped by a quality gate (C-1/C-3) versus actually reaching the vote.
VOTING_WINDOW_MIN_FRAMES = 3
VOTING_WINDOW_MAX_FRAMES = 5


@dataclass(frozen=True)
class VotingWindowStats:
    """Log-only bookkeeping for one `/recognize` request's C-4 voting
    window -- never influences `decide_from_scores` itself (that function
    stays pure and unaware of this module, per `recognize.py`'s existing
    separation of concerns). Useful for exactly the measurement the C-1
    enforce criterion needs: the fraction of submitted frames a quality gate
    skipped, watched over time (TSD D-3: "< 1-2% over 1-2 weeks, per
    device_class") before flipping `Settings.quality_gate_enforcing` on.
    """

    frames_submitted: int
    frames_voted: int
    frames_skipped_quality_gate: int

    @property
    def skip_rate(self) -> float:
        if self.frames_submitted == 0:
            return 0.0
        return self.frames_skipped_quality_gate / self.frames_submitted

    @property
    def within_recommended_window(self) -> bool:
        """Whether `frames_submitted` falls inside TSD D-3 C-4's explicit
        3-5 frame window. Log-only signal -- never blocks a request (a
        client submitting outside this range is a calibration/config
        concern, not a per-request failure)."""
        return VOTING_WINDOW_MIN_FRAMES <= self.frames_submitted <= VOTING_WINDOW_MAX_FRAMES
