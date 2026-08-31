"""`/recognize` pipeline: decode -> detect -> align -> (fake) liveness ->
embed -> ANN gallery search -> threshold/margin decision -> temporal voting
(IN-03, FR-INF-01/02/03).

**Deliberate gaps, NOT implemented here** (see the IN-03 task brief for the
tracking tickets):

1. **IN-02 (device auth)**: `POST /recognize` has NO device authentication.
   The router (`ai_inference.main`) documents this at the endpoint
   definition; this module has no auth concept at all. MUST be closed
   before production.
2. **IN-04 (real liveness/anti-spoofing)**: `placeholder_liveness_score()`
   below is a FIXED constant, not a real check. See its docstring.
3. **IN-06 (event emission)**: this module never calls backend's
   `POST /access-events`. It only computes and returns a decision.
4. **IN-07 (atomic model+gallery switch)**: the PRODUCTION model version is
   read fresh from `models` on every single request
   (`gallery.get_current_production_model_version`) -- no caching, no
   atomic blue/green switch mechanism. Good enough for v1; IN-07 can add
   caching later.
5. **`SPOOF_SUSPECTED`**: never produced here (needs IN-04's real liveness).
   The only decisions this module ever returns are `GRANTED` and `UNKNOWN`.

`decide_from_scores` (and its `FrameCandidate`/`RecognitionResult` types) is
pure Python -- no cv2/torch/DB -- and is fully unit tested
(`tests/test_recognize.py`). `run_recognition` is the real orchestration
(decode/detect/align/embed/DB) and is NOT covered by automated tests (needs
cv2 + torch + a real Postgres gallery) -- it is verified live, per this
project's established convention for this class of code (see
`ai_training.quality.pipeline`'s module docstring for the same convention).
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ai_inference.config import Settings

# Liveness is NOT implemented until IN-04. This constant is deliberately
# named to make misuse loud: importing/using it anywhere near "this proves
# the subject is live" would be wrong. It always returns the same value
# regardless of input.
_LIVENESS_PLACEHOLDER_SCORE = 1.0


def placeholder_liveness_score(_aligned_crop: Any) -> float:
    """**NOT A REAL LIVENESS/ANTI-SPOOFING CHECK.** Always returns a fixed
    score (`1.0`) no matter what is passed in. This exists only so the
    `/recognize` response shape has a `liveness_score` field populated
    ahead of IN-04, which will implement real passive/active PAD (e.g.
    MiniFASNet). Do NOT treat this value as evidence of anything, and do
    NOT derive a `SPOOF_SUSPECTED` decision from it -- see module docstring
    gap list, item 2 and 5.
    """
    return _LIVENESS_PLACEHOLDER_SCORE


@dataclass(frozen=True)
class FrameCandidate:
    """One frame's gallery-search result, already collapsed to per-user
    max-fusion scores (`ai_inference.gallery.search_top_k` rows grouped by
    `user_id`, keeping each user's best score) and reduced to the top-1 and
    top-2 (different users). `top1_user_id`/`top1_similarity` are both
    `None` when the frame contributed no candidate at all (no face detected
    in the frame, or no PRODUCTION model / empty gallery)."""

    top1_user_id: str | None
    top1_similarity: float | None
    top2_similarity: float | None = None


@dataclass(frozen=True)
class RecognitionResult:
    decision: str  # "GRANTED" | "UNKNOWN"
    user_id: str | None
    similarity: float


def frame_passes_threshold(
    candidate: FrameCandidate, *, threshold: float, margin: float
) -> tuple[str, float] | None:
    """Per-frame GRANT check (task brief step 7): `top1 >= threshold` AND
    (no top2 OR `top1 - top2 >= margin`). Returns `(user_id, top1_similarity)`
    if this frame's top1 passes, else `None` (this frame is UNKNOWN, never
    DENIED -- DENIED needs a real liveness/spoof signal this task doesn't
    have, see module docstring gap list)."""
    if candidate.top1_user_id is None or candidate.top1_similarity is None:
        return None
    if candidate.top1_similarity < threshold:
        return None
    if candidate.top2_similarity is not None:
        if candidate.top1_similarity - candidate.top2_similarity < margin:
            return None
    return candidate.top1_user_id, candidate.top1_similarity


def decide_from_scores(
    candidates: list[FrameCandidate],
    *,
    threshold: float,
    margin: float,
    min_frames_for_grant: int,
) -> RecognitionResult:
    """Pure decision logic (task brief steps 7+8): per-frame threshold+margin
    check, then cross-frame temporal voting. No DB/torch/cv2 involved --
    fully unit-testable with hand-computed inputs.

    Voting rule (recommendations.md SS5: accept if >=2 of 3-5 frames pass
    tau): a `user_id` is GRANTED only if it passes the per-frame check in at
    least `min_frames_for_grant` of the submitted frames. If no user_id
    reaches that count, the final decision is `UNKNOWN` with `user_id=None`.

    `similarity` on a GRANTED result is the MAX `top1_similarity` among the
    frames that voted for the winner (chosen over "average": it reports the
    single strongest piece of evidence actually collected, the same
    max-fusion spirit already used per-frame -- the task brief explicitly
    allows either choice, documented here as the one implemented).

    Ties in vote count are broken by whichever candidate has the higher such
    max similarity; this is deterministic (no ordering dependence on dict
    iteration) because Python's `max()` compares the full `(votes, score)`
    tuple.
    """
    votes: dict[str, list[float]] = {}
    for candidate in candidates:
        passed = frame_passes_threshold(candidate, threshold=threshold, margin=margin)
        if passed is None:
            continue
        user_id, similarity = passed
        votes.setdefault(user_id, []).append(similarity)

    eligible = {
        user_id: scores
        for user_id, scores in votes.items()
        if len(scores) >= min_frames_for_grant
    }
    if not eligible:
        return RecognitionResult(decision="UNKNOWN", user_id=None, similarity=0.0)

    winner_user_id, winner_scores = max(
        eligible.items(), key=lambda item: (len(item[1]), max(item[1]))
    )
    return RecognitionResult(
        decision="GRANTED", user_id=winner_user_id, similarity=max(winner_scores)
    )


def _decode_frame_bgr(frame_base64: str) -> Any:
    """Base64 -> BGR numpy array, mirroring
    `ai_training.evaluation.metrics._decode_media_to_frames`'s single-image
    branch (`cv2.imdecode`). Returns `None` if decoding fails (malformed
    base64/not a valid JPEG-or-PNG) rather than raising -- treated the same
    as "no face detected" by the caller (skip this frame, don't fail the
    whole request)."""
    try:
        import cv2
        import numpy as np
    except ImportError as exc:  # pragma: no cover - depends on extras
        raise RuntimeError(
            "run_recognition requires the 'ml' extra (uv sync --extra ml): "
            "opencv-python-headless (pulled in transitively via ai-training)."
        ) from exc
    try:
        raw = base64.b64decode(frame_base64, validate=False)
    except (ValueError, TypeError):
        return None
    buffer = np.frombuffer(raw, dtype=np.uint8)
    if buffer.size == 0:
        return None
    frame = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    return frame


def _collapse_to_top_candidates(rows: list[tuple[str, float]]) -> FrameCandidate:
    """Max-fusion collapse (task brief step 6): many raw
    `(user_id, similarity)` template rows -> best score per user_id -> top-1
    and top-2 (different users)."""
    best_per_user: dict[str, float] = {}
    for user_id, similarity in rows:
        if user_id not in best_per_user or similarity > best_per_user[user_id]:
            best_per_user[user_id] = similarity

    if not best_per_user:
        return FrameCandidate(top1_user_id=None, top1_similarity=None, top2_similarity=None)

    ranked = sorted(best_per_user.items(), key=lambda item: item[1], reverse=True)
    top1_user_id, top1_similarity = ranked[0]
    top2_similarity = ranked[1][1] if len(ranked) > 1 else None
    return FrameCandidate(
        top1_user_id=top1_user_id, top1_similarity=top1_similarity, top2_similarity=top2_similarity
    )


def run_recognition(
    frames_base64: list[str],
    settings: Settings,
    *,
    embedder: Any,
    cursor: Any,
) -> tuple[RecognitionResult, str]:
    """Full orchestration for `POST /recognize` (task brief steps 1-8).

    `embedder` is anything exposing `.embed(aligned_crop) -> list[float]`
    (real: `ai_training.embedding.embedder.EmbedderInterface`, e.g. from
    `AdaFaceModelLoader.load(ModelKind.EMBEDDER).handle`).
    `cursor` is a `ai_inference.gallery.Cursor`-shaped DB-API cursor already
    connected via the `ai_inference_ro` role.

    Returns `(RecognitionResult, model_version)` -- `model_version` is `""`
    when there is no PRODUCTION model (fail-secure: every frame is treated
    as UNKNOWN, this is never a 500 -- task brief step 6).

    Not covered by automated tests (needs cv2 + torch + a real DB) -- see
    module docstring.
    """
    from ai_inference import gallery

    production_version = gallery.get_current_production_model_version(cursor)
    if production_version is None:
        return RecognitionResult(decision="UNKNOWN", user_id=None, similarity=0.0), ""

    from ai_training.embedding.alignment import align_face
    from ai_training.quality.pose import detect_face_and_landmarks

    candidates: list[FrameCandidate] = []
    for frame_b64 in frames_base64:
        frame_bgr = _decode_frame_bgr(frame_b64)
        if frame_bgr is None:
            continue  # malformed frame: skip, not a hard failure (step 1)

        detection = detect_face_and_landmarks(frame_bgr)
        if detection is None:
            continue  # no face in this frame: skip, not a hard failure (step 2)

        aligned = align_face(frame_bgr, detection.alignment_landmarks_5pt())
        # Liveness placeholder -- see module docstring gap list, item 2.
        # Deliberately not used in any decision below; computed only so a
        # real value (rather than a hardcoded literal duplicated at the call
        # site) backs the response field.
        placeholder_liveness_score(aligned)

        vector = embedder.embed(aligned)
        rows = gallery.search_top_k(
            cursor,
            embedding=vector,
            model_version=production_version,
            k=settings.ann_top_k,
        )
        candidates.append(_collapse_to_top_candidates(rows))

    result = decide_from_scores(
        candidates,
        threshold=settings.similarity_threshold,
        margin=settings.margin_threshold,
        min_frames_for_grant=settings.min_frames_for_grant,
    )
    return result, production_version


def run_recognition_timed(
    frames_base64: list[str],
    settings: Settings,
    *,
    embedder: Any,
    cursor: Any,
) -> dict[str, Any]:
    """`run_recognition` wrapped with the FR-INF-02 `latency_ms` measurement
    and assembled into the exact `/recognize` response dict (task brief step
    9). Split out from `run_recognition` so the pure timing/assembly concern
    doesn't complicate that function's already-long orchestration body."""
    start = time.perf_counter()
    result, model_version = run_recognition(
        frames_base64, settings, embedder=embedder, cursor=cursor
    )
    latency_ms = int((time.perf_counter() - start) * 1000)
    return {
        "decision": result.decision,
        "user_id": result.user_id,
        "similarity": result.similarity,
        "liveness_score": _LIVENESS_PLACEHOLDER_SCORE,
        "model_version": model_version,
        "latency_ms": latency_ms,
    }
