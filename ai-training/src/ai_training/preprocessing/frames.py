"""Frame extraction & pose-bin re-exports (TR-01 stub, superseded by TR-02).

TR-01 sketched a flat yaw-only pose-bin scheme (`POSE_BIN_YAWS` from -90 to
+90 degrees, "back-of-head frames discarded") based on the ORIGINAL (later
corrected) assumption that enrollment was a full 360-degree body/camera
rotation. **ASM-03 was corrected on 2026-08-30** (see
`documentation/fsd/FSD-AI.md`): the capture is a head-orientation sweep
only (yaw+pitch, body/camera fixed, face always visible — no back-of-head
segment exists to discard). TR-02 replaces the pose-bin model with a
12-clock-position (yaw, pitch) mapping in `ai_training.quality.pose`, and
the real (in-memory, `cv2`-backed) video decoder now lives in
`ai_training.quality.pipeline.extract_frames`.

This module is kept only as a thin compatibility re-export so any external
caller importing `ai_training.preprocessing.frames` does not hard-crash;
new code should import directly from `ai_training.quality.pose` /
`ai_training.quality.pipeline`.
"""

from __future__ import annotations

from ai_training.quality.pipeline import extract_frames as extract_frames
from ai_training.quality.pose import CLOCK_POSITIONS as CLOCK_POSITIONS
from ai_training.quality.pose import clock_position_targets as clock_position_targets
from ai_training.quality.pose import nearest_clock_position as nearest_clock_position

__all__ = [
    "extract_frames",
    "CLOCK_POSITIONS",
    "clock_position_targets",
    "nearest_clock_position",
]
