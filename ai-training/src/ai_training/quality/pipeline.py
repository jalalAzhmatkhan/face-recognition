"""End-to-end QC pipeline: video bytes -> per-clock-position QCReport (TR-02).

Requires the `ml` extra (`cv2`, `mediapipe`) — lazily imported, so this
module is importable (and its pure-math neighbours testable) without it.
Not covered by automated tests (would require real/synthetic video +
mediapipe installed); see the ai-engineer task's manual-verification
checklist for how to exercise this against a real recording.
"""

from __future__ import annotations

import contextlib
import math
import os
import tempfile
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
    `blur_variance_min`/`brightness_min`/`brightness_max`).

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
    frame: Any, settings: QCSettings, neutral_pose: tuple[float, float] | None = None
) -> FrameQuality | None:
    detection = detect_face_and_landmarks(
        frame, model_path=settings.face_landmarker_model_path or None
    )
    if detection is None:
        return None

    height, width = frame.shape[:2]
    raw_yaw, raw_pitch, _roll = estimate_pose_from_landmarks(detection, (width, height))
    yaw, pitch = apply_neutral_offset(raw_yaw, raw_pitch, neutral_pose, settings=settings)
    position = nearest_clock_position(
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
        import numpy as np

        cv2 = _require_cv2()  # inside the try: a missing `ml` extra must not raise either
        buffer = np.frombuffer(photo_bytes, dtype=np.uint8)
        frame = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
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
    report = QCReport(
        session_id=session_id,
        overall=overall,
        coverage_ratio=coverage_ratio,
        positions=position_results,
        generated_at=datetime.now(UTC),
    )
    return report, by_position
