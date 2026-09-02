"""End-to-end QC pipeline: video bytes -> per-clock-position QCReport (TR-02).

Requires the `ml` extra (`cv2`, `mediapipe`) — lazily imported, so this
module is importable (and its pure-math neighbours testable) without it.
Not covered by automated tests (would require real/synthetic video +
mediapipe installed); see the ai-engineer task's manual-verification
checklist for how to exercise this against a real recording.
"""

from __future__ import annotations

import contextlib
import logging
import math
import os
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ai_training.config import QCSettings
from ai_training.quality import metrics as qmetrics
from ai_training.quality.pose import (
    CLOCK_POSITIONS,
    clock_position_targets,
    detect_face_and_landmarks,
    estimate_pose_from_landmarks,
    nearest_clock_position,
)
from ai_training.quality.report import PositionResult, QCReport

logger = logging.getLogger(__name__)


def _require_cv2() -> Any:
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - depends on extras
        raise RuntimeError(
            "QC video decode requires the 'ml' extra (uv sync --extra ml): opencv-python-headless."
        ) from exc
    return cv2


@dataclass
class FrameQuality:
    """Per-frame QC evaluation. `frame` is kept (BGR ndarray) so TR-03's
    embedding extraction can reuse the exact same decoded/selected frames
    without a second, redundant video decode."""

    frame: Any
    position: str
    blur: float
    brightness: float
    face_ratio: float
    yaw: float
    pitch: float
    passed: bool
    reasons: list[str] = field(default_factory=list)


def extract_frames(video_bytes: bytes, *, fps_sample: float = 6.0) -> list[Any]:
    """Decode an in-memory video buffer (webm/mp4) into sampled BGR frames.

    Media-at-rest rule (NFR-SEC-02 / repo CLAUDE.md non-negotiable #1):
    video bytes must never be persisted permanently on local disk.
    `cv2.VideoCapture` cannot decode directly from a Python `bytes` buffer,
    so this writes the bytes to an OS temp file that exists ONLY for the
    duration of this call and is removed in a `finally` block even if
    decoding raises — the same "transient scratch, deleted immediately"
    pattern the rest of the repo uses for tmpfs/in-memory buffers, just
    necessarily backed by a real (very short-lived) file because that's
    the only interface OpenCV's demuxer accepts.
    """
    cv2 = _require_cv2()
    fd, path = tempfile.mkstemp(suffix=".webm")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(video_bytes)
        capture = cv2.VideoCapture(path)
        try:
            if not capture.isOpened():
                raise RuntimeError("failed to open enrollment video for decoding")
            source_fps = capture.get(cv2.CAP_PROP_FPS) or fps_sample
            step = max(1, round(source_fps / fps_sample))
            frames: list[Any] = []
            index = 0
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                if index % step == 0:
                    frames.append(frame)
                index += 1
            return frames
        finally:
            capture.release()
    finally:
        with contextlib.suppress(OSError):
            os.remove(path)


def resolve_qc_settings(cursor: Any, settings: QCSettings) -> QCSettings:
    """Merge the ADMIN-configurable "System Parameter" enrollment-capture-
    quality override (`system_parameters` key `enrollment_capture_quality`,
    `backend/app/services/system_parameter_service.py`) on top of the
    env-driven `QCSettings` defaults, for the fields the admin menu exposes
    (`min_blur_variance`/`min_brightness`/`max_brightness` -> this class's
    `blur_variance_min`/`brightness_min`/`brightness_max`, plus
    `pose_tolerance_deg` straight through).

    The menu's `yaw_gain`/`pitch_gain`/`min_pose_radius` are deliberately NOT
    mapped here: they correct the FRONTEND's landmark-ratio pose estimator,
    which under-reports pitch badly. This side uses `cv2.solvePnP`, which
    reports true degrees and needs no such correction -- applying a gain here
    would double-count it. `pose_tolerance_deg` is the knob that belongs to
    this side, and it is in the same parameter so the two halves of the gate
    can be retuned together.

    No row saved yet (ADMIN has never touched the menu) -> `settings`
    returned completely unchanged, byte-identical to before this function
    existed. This is the SAME "override on top of an env/artefact default,
    never the source of truth" shape `ai_inference.pipeline.threshold_
    resolution.resolve_mode_params` already uses for `recognition_configs`
    (EC-IN-04/06) — kept as a plain function taking a cursor (not a class)
    for the same reason: this package has no ORM, only raw-SQL repos.
    """
    from ai_training.db.system_parameters_repo import get_enrollment_quality_override

    override = get_enrollment_quality_override(cursor)
    if not override:
        return settings

    updates: dict[str, float] = {}
    if "min_blur_variance" in override:
        updates["blur_variance_min"] = float(override["min_blur_variance"])
    if "min_brightness" in override:
        updates["brightness_min"] = float(override["min_brightness"])
    if "max_brightness" in override:
        updates["brightness_max"] = float(override["max_brightness"])
    if "pose_tolerance_deg" in override:
        updates["pose_tolerance_deg"] = float(override["pose_tolerance_deg"])
    if not updates:
        return settings
    return settings.model_copy(update=updates)


def apply_neutral_offset(
    yaw: float,
    pitch: float,
    neutral: tuple[float, float] | None,
    *,
    settings: QCSettings,
) -> tuple[float, float]:
    """Re-express `(yaw, pitch)` RELATIVE to the subject's own neutral
    (straight-at-the-camera) reading.

    `ai_training.quality.pose`'s clock geometry assumes a neutral face
    measures `(0, 0)`, but `estimate_pose_from_landmarks` does not deliver
    that: solvePnP against the generic 3D model reports a large POSITIVE
    (upward) pitch for a frontal face -- a real portrait measured +24.3 deg
    against a +-25 deg `pitch_range_deg`, recorded live in `pose.py`'s own
    comments. Uncorrected, that bias makes the whole BOTTOM half of the
    clock unreachable: 12 o'clock is satisfied by sitting still, while 6
    o'clock would need roughly twice `pitch_range_deg` of real downward
    tilt, and every genuine 4/5/7/8 lands one or two sectors too high
    because the measured ANGLE is rotated upward too (found live during
    pilot capture -- "jam 4-8 tidak terdeteksi").

    The baseline comes from the session's own frontal photo (see
    `ai_training.db.enrollment_repo.get_frontal_photo`), so it needs no
    per-camera or per-face tuning and stays correct if the estimator is
    ever swapped. The frontend applies the identical correction with its
    own baseline and its own estimator
    (`frontend/src/features/enrollment-capture/headPose.ts`).

    `None` means "no baseline available" -> unchanged, pre-calibration
    behaviour. The offset is capped at ONE FULL axis range (not half): the
    genuine bias here is already ~97% of `pitch_range_deg`, so a tighter cap
    would silently remove only part of it and leave the bottom half of the
    clock just as unreachable (caught by
    `tests/test_neutral_pose_offset.py`). One range is the largest shift the
    geometry can express anyway, so it still bounds a mis-measured baseline.
    """
    if neutral is None:
        return yaw, pitch
    neutral_yaw, neutral_pitch = neutral
    max_yaw_offset = settings.yaw_range_deg
    max_pitch_offset = settings.pitch_range_deg
    clamped_yaw = min(max_yaw_offset, max(-max_yaw_offset, neutral_yaw))
    clamped_pitch = min(max_pitch_offset, max(-max_pitch_offset, neutral_pitch))
    return yaw - clamped_yaw, pitch - clamped_pitch


def _evaluate_frame(
    frame: Any,
    settings: QCSettings,
    neutral_pose: tuple[float, float] | None = None,
    declared_position: str | None = None,
) -> FrameQuality | None:
    """Evaluate one decoded frame.

    `declared_position` ("01".."12") is the position the frame was CAPTURED
    FOR, which only the photo path knows -- a sweep frame is uploaded with
    its own `clock_position` (backend migration `e4b9d2f6a8c3`). Given it,
    the frame is scored against THAT target instead of whichever target it
    happens to land nearest.

    That difference matters. `nearest_clock_position` has no radius gate, so
    a frame always lands somewhere: on the video path a pose that drifted
    into a neighbouring sector is silently re-labelled and can PASS as that
    neighbour, quietly leaving the intended position uncovered. Scoring
    against the declared target instead turns the same drift into an honest
    `pose_out_of_range` on the position the subject was actually asked for.
    `None` (the video path) keeps the nearest-position behaviour unchanged.
    """
    detection = detect_face_and_landmarks(
        frame, model_path=settings.face_landmarker_model_path or None
    )
    if detection is None:
        return None

    height, width = frame.shape[:2]
    raw_yaw, raw_pitch, _roll = estimate_pose_from_landmarks(detection, (width, height))
    yaw, pitch = apply_neutral_offset(raw_yaw, raw_pitch, neutral_pose, settings=settings)
    position = declared_position or nearest_clock_position(
        yaw, pitch, yaw_range_deg=settings.yaw_range_deg, pitch_range_deg=settings.pitch_range_deg
    )
    blur = qmetrics.blur_score(frame)
    brightness = qmetrics.brightness_score(frame)
    face_ratio = qmetrics.face_size_ratio(detection.bbox_wh, (width, height))

    reasons: list[str] = []
    if blur < settings.blur_variance_min:
        reasons.append("blurry")
    if not (settings.brightness_min <= brightness <= settings.brightness_max):
        reasons.append("bad_lighting")
    if face_ratio < settings.face_ratio_min:
        reasons.append("face_too_small")

    target = clock_position_targets(settings.yaw_range_deg, settings.pitch_range_deg)[position]
    pose_error = math.hypot(yaw - target.yaw_deg, pitch - target.pitch_deg)
    if pose_error > settings.pose_tolerance_deg:
        reasons.append("pose_out_of_range")

    return FrameQuality(
        frame=frame,
        position=position,
        blur=blur,
        brightness=brightness,
        face_ratio=face_ratio,
        yaw=yaw,
        pitch=pitch,
        passed=not reasons,
        reasons=reasons,
    )


def decode_image(photo_bytes: bytes) -> Any | None:
    """Decode JPEG/PNG bytes to a BGR frame, or `None` if the bytes are not
    a readable image. Never raises — a single corrupt sweep frame must cost
    that frame, not the whole session (its position simply has one fewer
    candidate, and falls back to `no_face_detected` if it had no others)."""
    try:
        import numpy as np

        cv2 = _require_cv2()  # inside the try: a missing `ml` extra must not raise either
        frame = cv2.imdecode(np.frombuffer(photo_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    except Exception:  # noqa: BLE001 - see docstring
        return None
    return frame


def estimate_neutral_pose(photo_bytes: bytes, settings: QCSettings) -> tuple[float, float] | None:
    """`(yaw, pitch)` of the session's frontal photo, for use as the neutral
    baseline in `apply_neutral_offset` -- or `None` if it cannot be
    established (undecodable image, no face found, pose estimation failed).

    Deliberately never raises: calibration is an ACCURACY improvement, not a
    correctness precondition, so a session whose frontal photo cannot be
    read must still go through QC exactly as it did before calibration
    existed rather than failing outright.
    """
    try:
        frame = decode_image(photo_bytes)
        if frame is None:
            return None
        detection = detect_face_and_landmarks(
            frame, model_path=settings.face_landmarker_model_path or None
        )
        if detection is None:
            return None
        height, width = frame.shape[:2]
        yaw, pitch, _roll = estimate_pose_from_landmarks(detection, (width, height))
    except Exception:  # noqa: BLE001 - see docstring: never block QC on calibration
        return None
    return yaw, pitch


def run_quality_check(
    video_bytes: bytes,
    *,
    session_id: str,
    settings: QCSettings,
    neutral_pose: tuple[float, float] | None = None,
) -> tuple[QCReport, dict[str, list[FrameQuality]]]:
    """Run the full QC pipeline and return `(report, frames_by_position)`.

    `frames_by_position` (ALL evaluated frames per clock position, not just
    the passing ones) is returned so the caller (the Celery task, on QC
    PASS) can feed it straight into TR-03's embedding extraction without
    re-decoding the video.

    `neutral_pose` is the subject's straight-at-the-camera `(yaw, pitch)`
    baseline, normally from `estimate_neutral_pose` over the session's
    frontal photo. `None` (the default) keeps the exact pre-calibration
    behaviour, which is what the batch re-embed/backfill jobs rely on for
    legacy sessions -- see `apply_neutral_offset` for why it matters.
    """
    frames = extract_frames(video_bytes, fps_sample=settings.sample_fps)
    by_position: dict[str, list[FrameQuality]] = {position: [] for position in CLOCK_POSITIONS}
    for frame in frames:
        evaluated = _evaluate_frame(frame, settings, neutral_pose)
        if evaluated is not None:
            by_position[evaluated.position].append(evaluated)

    return _build_report(by_position, session_id=session_id, settings=settings), by_position


def run_photo_quality_check(
    photos: Sequence[tuple[str, bytes]],
    *,
    session_id: str,
    settings: QCSettings,
    neutral_pose: tuple[float, float] | None = None,
) -> tuple[QCReport, dict[str, list[FrameQuality]]]:
    """Photo-path counterpart of `run_quality_check` (FR-ENR-06).

    `photos` is `(clock_position, image_bytes)` pairs, positions as
    "01".."12" — the sweep frames a session uploaded, each already labelled
    with the position it was captured for. Ordering and duplicates are
    irrelevant: several frames per position is the normal case (the wizard
    captures a burst), and every frame is scored independently.

    Returns the SAME `(report, frames_by_position)` shape as the video path,
    so the caller's PASS handling and TR-03 embedding extraction are shared
    verbatim between the two.

    Frames that cannot be decoded, or that show no face, are dropped rather
    than failing the session — a position with no surviving candidate
    reports `no_face_detected`, exactly as an unreached position does on the
    video path.
    """
    by_position: dict[str, list[FrameQuality]] = {position: [] for position in CLOCK_POSITIONS}
    for position, image_bytes in photos:
        if position not in by_position:
            logger.warning(
                "ai_training.quality.unknown_clock_position session_id=%s position=%s",
                session_id,
                position,
            )
            continue
        frame = decode_image(image_bytes)
        if frame is None:
            logger.warning(
                "ai_training.quality.undecodable_photo session_id=%s position=%s",
                session_id,
                position,
            )
            continue
        evaluated = _evaluate_frame(frame, settings, neutral_pose, declared_position=position)
        if evaluated is not None:
            by_position[position].append(evaluated)

    return _build_report(by_position, session_id=session_id, settings=settings), by_position


def _build_report(
    by_position: dict[str, list[FrameQuality]],
    *,
    session_id: str,
    settings: QCSettings,
) -> QCReport:
    """Fold per-position frame evaluations into the session-level verdict.
    Shared by both capture shapes so a photo session and a legacy video
    session are judged by identical rules."""
    position_results: list[PositionResult] = []
    passed_count = 0
    for position in CLOCK_POSITIONS:
        candidates = by_position[position]
        passing = [c for c in candidates if c.passed]
        if passing:
            position_results.append(
                PositionResult(
                    position=position,
                    passed=True,
                    reasons=[],
                    best_score=max(c.blur for c in passing),
                )
            )
            passed_count += 1
        elif candidates:
            reasons = sorted({reason for c in candidates for reason in c.reasons})
            position_results.append(
                PositionResult(position=position, passed=False, reasons=reasons)
            )
        else:
            position_results.append(
                PositionResult(position=position, passed=False, reasons=["no_face_detected"])
            )

    coverage_ratio = passed_count / len(CLOCK_POSITIONS)
    overall = "PASS" if coverage_ratio >= settings.min_pass_ratio else "REJECTED_QUALITY"
    return QCReport(
        session_id=session_id,
        overall=overall,
        coverage_ratio=coverage_ratio,
        positions=position_results,
        generated_at=datetime.now(UTC),
    )
