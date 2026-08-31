"""`/recognize` pipeline: decode -> detect -> liveness -> align -> embed ->
ANN gallery search -> threshold/margin decision -> temporal voting (IN-03,
FR-INF-01/02/03; liveness/PAD landed in IN-04, closing gap 2/5 below).
Per-stage Prometheus latency histograms (`ai_inference.metrics`) and the
`decisions_total` counter are recorded here too (IN-05, NFR-PRF-01/02).

**Deliberate gaps, NOT implemented here** (see the IN-03 task brief for the
tracking tickets):

1. ~~IN-02 (device auth)~~ **CLOSED (IN-02)**: `POST /recognize` requires a
   device credential via `ai_inference.auth_dependency.get_current_device_id`
   (wired at the router in `ai_inference.main`, not in this module -- this
   module still has no auth concept of its own, by design).
2. ~~IN-04 (real liveness/anti-spoofing)~~ **CLOSED (IN-04)**: every frame
   is now scored by `ai_training.liveness.detector.LivenessDetector`
   (default real backend: `MiniFASNetLivenessDetector`, an ensemble of two
   MiniFASNet models -- see that module's docstring for the full
   procedure/reinterpretation of the upstream score). A frame whose score
   falls below `settings.liveness_threshold` is flagged spoof-suspect and
   is EXCLUDED from identity voting entirely (see `decide_from_scores`).
3. ~~IN-06 (event emission)~~ **CLOSED (IN-06)**: this module itself still
   never calls backend's `POST /access-events` -- it only computes and
   returns a decision, by design (no HTTP/backend concern belongs in the
   pure pipeline). The emission itself is dispatched by
   `ai_inference.main`'s `/recognize` handler (fire-and-forget via
   `BackgroundTasks`, see `ai_inference.events`), using this function's
   returned `RecognitionResult`/`model_version`/`liveness_scores`.
4. **IN-07 (atomic model+gallery switch)**: the PRODUCTION model version is
   read fresh from `models` on every single request
   (`gallery.get_current_production_model_version`) -- no caching, no
   atomic blue/green switch mechanism. Good enough for v1; IN-07 can add
   caching later.
5. ~~`SPOOF_SUSPECTED`~~ **CLOSED (IN-04)**: `decide_from_scores` can now
   return `"SPOOF_SUSPECTED"` -- see its docstring for the exact voting
   rule and priority order.

`decide_from_scores` (and its `FrameCandidate`/`RecognitionResult` types) is
pure Python -- no cv2/torch/DB -- and is fully unit tested
(`tests/test_recognize.py`). `run_recognition` is the real orchestration
(decode/detect/liveness/align/embed/DB) and is NOT covered by automated
tests (needs cv2 + torch + a real Postgres gallery) -- it is verified live,
per this project's established convention for this class of code (see
`ai_training.quality.pipeline`'s module docstring for the same convention).
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ai_inference.metrics import decision_latency_seconds, decisions_total, stage_latency_seconds

if TYPE_CHECKING:
    from ai_inference.config import Settings

# Fallback used ONLY when no real `LivenessDetector` handle is available at
# all (e.g. `run_recognition` called without one -- should not happen on the
# real `/recognize` path, where `ai_inference.main` always loads
# `ModelKind.LIVENESS` first, see that module). Kept named/scoped narrowly
# (not reused as a "the subject is live" claim anywhere) so misuse stays
# loud, same spirit as IN-03's original `placeholder_liveness_score`, which
# this replaces as the primary mechanism now that IN-04 has landed.
_LIVENESS_FALLBACK_SCORE = 1.0


@dataclass(frozen=True)
class FrameCandidate:
    """One frame's gallery-search result, already collapsed to per-user
    max-fusion scores (`ai_inference.gallery.search_top_k` rows grouped by
    `user_id`, keeping each user's best score) and reduced to the top-1 and
    top-2 (different users). `top1_user_id`/`top1_similarity` are both
    `None` when the frame contributed no candidate at all (no face detected
    in the frame, or no PRODUCTION model / empty gallery, OR the frame was
    flagged spoof-suspect and therefore never reached gallery search --
    see `spoof_suspect` below and `run_recognition`).

    `spoof_suspect` (IN-04): `True` when this frame's liveness score fell
    below `settings.liveness_threshold`. Such a frame is a "spoof vote" --
    completely separate from the identity vote (`top1_user_id` is always
    `None` on a spoof-suspect frame; identity matching is skipped entirely
    for it, see `run_recognition`, per NFR-SEC-06: a photo/screen replay of
    an otherwise-authorized person must still be rejected)."""

    top1_user_id: str | None
    top1_similarity: float | None
    top2_similarity: float | None = None
    spoof_suspect: bool = False


@dataclass(frozen=True)
class RecognitionResult:
    decision: str  # "GRANTED" | "UNKNOWN" | "SPOOF_SUSPECTED"
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
    """Pure decision logic (task brief steps 7+8, extended by IN-04): per-frame
    threshold+margin check plus a separate per-frame "spoof vote", then
    cross-frame temporal voting on BOTH. No DB/torch/cv2 involved -- fully
    unit-testable with hand-computed inputs.

    **Decision priority (IN-04, documented here because it is the one
    non-obvious rule this function implements): `SPOOF_SUSPECTED` > `GRANTED`
    > `UNKNOWN`.** Security wins over convenience: if enough frames look
    spoofed to reach `min_frames_for_grant`, the final decision is
    `SPOOF_SUSPECTED` (`user_id=None`, `similarity=0.0`) EVEN IF some other
    frames in the same batch separately voted a real user_id all the way to
    GRANTED-eligibility -- an attacker should not be able to "drown out" a
    spoof signal by mixing in enough live-looking frames (e.g. holding up a
    photo for most of the capture window but glancing at the camera for a
    couple of real frames). The spoof vote reuses the SAME
    `min_frames_for_grant` threshold as identity voting (no separate voting
    config, per task brief) -- both express "how many of the submitted
    frames must agree before we act on it".

    Identity voting rule (recommendations.md SS5: accept if >=2 of 3-5
    frames pass tau), unchanged from IN-03: a `user_id` is GRANTED only if
    it passes the per-frame threshold+margin check in at least
    `min_frames_for_grant` of the submitted frames. If no user_id reaches
    that count (and the spoof vote also didn't reach it), the final decision
    is `UNKNOWN` with `user_id=None`.

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
    spoof_votes = sum(1 for candidate in candidates if candidate.spoof_suspect)
    if spoof_votes >= min_frames_for_grant:
        return RecognitionResult(decision="SPOOF_SUSPECTED", user_id=None, similarity=0.0)

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
    liveness_detector: Any = None,
) -> tuple[RecognitionResult, str, list[float]]:
    """Full orchestration for `POST /recognize` (task brief steps 1-8, plus
    IN-04's liveness gate between detect and embed).

    `embedder` is anything exposing `.embed(aligned_crop) -> list[float]`
    (real: `ai_training.embedding.embedder.EmbedderInterface`, e.g. from
    `AdaFaceModelLoader.load(ModelKind.EMBEDDER).handle`).
    `liveness_detector` is anything exposing
    `.score(frame_bgr, bbox_xy, bbox_wh) -> float`
    (real: `ai_training.liveness.detector.LivenessDetector`, e.g. from
    `AdaFaceModelLoader.load(ModelKind.LIVENESS).handle`) -- `None` is
    accepted (falls back to `_LIVENESS_FALLBACK_SCORE` for every frame, see
    that constant's docstring) but the real `/recognize` endpoint
    (`ai_inference.main`) always passes a real detector.
    `cursor` is a `ai_inference.gallery.Cursor`-shaped DB-API cursor already
    connected via the `ai_inference_ro` role.

    Returns `(RecognitionResult, model_version, liveness_scores)` --
    `model_version` is `""` when there is no PRODUCTION model (fail-secure:
    every frame is treated as UNKNOWN, this is never a 500 -- task brief
    step 6). `liveness_scores` is the per-frame liveness score for every
    frame that made it far enough to have a detected face (parallel to, but
    not 1:1 positionally with, `frames_base64` -- frames with no decodable
    image or no detected face contribute nothing to it, same as they
    contribute no `FrameCandidate`).

    Not covered by automated tests (needs cv2 + torch + a real DB) -- see
    module docstring.
    """
    from ai_inference import gallery

    stage_start = time.perf_counter()
    production_version = gallery.get_current_production_model_version(cursor)
    stage_latency_seconds.labels(stage="overhead").observe(time.perf_counter() - stage_start)
    if production_version is None:
        decisions_total.labels(decision="UNKNOWN").inc()
        return RecognitionResult(decision="UNKNOWN", user_id=None, similarity=0.0), "", []

    from ai_training.embedding.alignment import align_face
    from ai_training.quality.pose import detect_face_and_landmarks

    candidates: list[FrameCandidate] = []
    liveness_scores: list[float] = []
    for frame_b64 in frames_base64:
        stage_start = time.perf_counter()
        frame_bgr = _decode_frame_bgr(frame_b64)
        if frame_bgr is None:
            stage_latency_seconds.labels(stage="detect").observe(time.perf_counter() - stage_start)
            continue  # malformed frame: skip, not a hard failure (step 1)

        detection = detect_face_and_landmarks(frame_bgr)
        stage_latency_seconds.labels(stage="detect").observe(time.perf_counter() - stage_start)
        if detection is None:
            continue  # no face in this frame: skip, not a hard failure (step 2)

        # IN-04 liveness gate: score BEFORE embedding/gallery search. A
        # spoof-suspect frame contributes a spoof vote but is NEVER passed
        # to gallery search -- no identity match from a suspected spoof
        # frame may contribute to a GRANTED decision (NFR-SEC-06).
        stage_start = time.perf_counter()
        if liveness_detector is not None:
            live_score = liveness_detector.score(
                frame_bgr, detection.bbox_xy, detection.bbox_wh
            )
        else:
            live_score = _LIVENESS_FALLBACK_SCORE
        stage_latency_seconds.labels(stage="liveness").observe(time.perf_counter() - stage_start)
        liveness_scores.append(live_score)

        if live_score < settings.liveness_threshold:
            candidates.append(
                FrameCandidate(
                    top1_user_id=None, top1_similarity=None, top2_similarity=None,
                    spoof_suspect=True,
                )
            )
            continue  # do NOT reach gallery search for this frame

        stage_start = time.perf_counter()
        aligned = align_face(frame_bgr, detection.alignment_landmarks_5pt())
        vector = embedder.embed(aligned)
        stage_latency_seconds.labels(stage="embed").observe(time.perf_counter() - stage_start)

        stage_start = time.perf_counter()
        rows = gallery.search_top_k(
            cursor,
            embedding=vector,
            model_version=production_version,
            k=settings.ann_top_k,
        )
        stage_latency_seconds.labels(stage="search").observe(time.perf_counter() - stage_start)
        candidates.append(_collapse_to_top_candidates(rows))

    stage_start = time.perf_counter()
    result = decide_from_scores(
        candidates,
        threshold=settings.similarity_threshold,
        margin=settings.margin_threshold,
        min_frames_for_grant=settings.min_frames_for_grant,
    )
    stage_latency_seconds.labels(stage="overhead").observe(time.perf_counter() - stage_start)
    decisions_total.labels(decision=result.decision).inc()
    return result, production_version, liveness_scores


def run_recognition_timed(
    frames_base64: list[str],
    settings: Settings,
    *,
    embedder: Any,
    cursor: Any,
    liveness_detector: Any = None,
) -> dict[str, Any]:
    """`run_recognition` wrapped with the FR-INF-02 `latency_ms` measurement
    and assembled into the exact `/recognize` response dict (task brief step
    9). Split out from `run_recognition` so the pure timing/assembly concern
    doesn't complicate that function's already-long orchestration body.

    **`liveness_score` representation (IN-04 decision)**: the MINIMUM
    liveness score among all frames that had a detected face (not the mean,
    and not just the winning frame's score). Chosen because this field's
    purpose is to help an operator/auditor spot spoofing risk in a
    response, and averaging would let a handful of clearly-live frames mask
    one clearly-spoofed frame -- the same "don't let good frames drown out
    a bad one" security principle `decide_from_scores`'s
    `SPOOF_SUSPECTED`-priority rule already applies to the decision itself.
    Falls back to `_LIVENESS_FALLBACK_SCORE` when no frame had a detected
    face at all (nothing was scored, decision is already `UNKNOWN` in that
    case).
    """
    start = time.perf_counter()
    result, model_version, liveness_scores = run_recognition(
        frames_base64, settings, embedder=embedder, cursor=cursor,
        liveness_detector=liveness_detector,
    )
    elapsed_seconds = time.perf_counter() - start
    decision_latency_seconds.observe(elapsed_seconds)
    latency_ms = int(elapsed_seconds * 1000)
    reported_liveness_score = min(liveness_scores) if liveness_scores else _LIVENESS_FALLBACK_SCORE
    return {
        "decision": result.decision,
        "user_id": result.user_id,
        "similarity": result.similarity,
        "liveness_score": reported_liveness_score,
        "model_version": model_version,
        "latency_ms": latency_ms,
    }
