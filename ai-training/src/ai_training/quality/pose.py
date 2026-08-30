"""Clock-position <-> (yaw, pitch) mapping + landmark-based pose estimation.

**ASM-03, corrected 2026-08-30 (FSD-AI.md)**: the enrollment capture is a
HEAD-ORIENTATION sweep, not a body/camera rotation. The subject's body stays
facing the camera the whole time; only head yaw (left/right) and pitch
(up/down) change, sweeping through the 12 clock positions and back to 12.
The face is visible to the camera at every position — there is no
back-of-head segment to discard, unlike the old (incorrect) "360 deg body
rotation" assumption this module used to encode via a flat yaw-only bin
list (`POSE_BIN_YAWS = -90..90`).

Geometry chosen here (documented, tunable via `QCSettings`):
- 12 o'clock = head tilted up (pitch max, yaw 0).
- 3 o'clock = head turned right (yaw max, pitch 0).
- 6 o'clock = head tilted down (pitch min, yaw 0).
- 9 o'clock = head turned left (yaw min, pitch 0).
- The other 8 positions interpolate around this circle every 30 degrees,
  i.e. clock position `c` (1..12) sits at angle `theta = 30 * (c % 12)`
  degrees clockwise from 12, with
  `yaw = yaw_range * sin(theta)`, `pitch = pitch_range * cos(theta)`.

This purely mathematical part (`clock_position_targets`,
`nearest_clock_position`) needs no `cv2`/`mediapipe` and is unit-tested
directly. The landmark-detection + `solvePnP` part
(`detect_face_and_landmarks`, `estimate_pose_from_landmarks`) lazily
imports `mediapipe`/`cv2` (the `ml` extra) and is only exercised through
`ai_training.quality.pipeline` against real frames (manual verification,
not automated tests — see module docstring there).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

CLOCK_POSITIONS: tuple[str, ...] = tuple(f"{i:02d}" for i in range(1, 13))  # "01".."12"


@dataclass(frozen=True)
class PoseTarget:
    position: str
    yaw_deg: float
    pitch_deg: float


def clock_position_targets(yaw_range_deg: float, pitch_range_deg: float) -> dict[str, PoseTarget]:
    """The 12 canonical (yaw, pitch) targets a well-executed capture should
    pass through, keyed by two-digit clock-position label ("01".."12")."""
    targets: dict[str, PoseTarget] = {}
    for i in range(1, 13):
        position = f"{i:02d}"
        theta = math.radians(30.0 * (i % 12))  # i=12 -> 12 % 12 == 0 -> theta=0 (top)
        yaw = yaw_range_deg * math.sin(theta)
        pitch = pitch_range_deg * math.cos(theta)
        targets[position] = PoseTarget(position=position, yaw_deg=yaw, pitch_deg=pitch)
    return targets


def nearest_clock_position(
    yaw_deg: float,
    pitch_deg: float,
    *,
    yaw_range_deg: float,
    pitch_range_deg: float,
) -> str:
    """Map an estimated (yaw, pitch) to the nearest of the 12 clock
    positions.

    Geometric idea: normalize yaw/pitch by their configured ranges so the
    12 target poses sit evenly on a unit circle (12 o'clock = straight up =
    (0, +1) after normalization, 3 o'clock = straight right = (+1, 0), ...)
    then pick whichever 30-degree sector of that circle the normalized
    point's angle falls into. This mirrors clock-face geometry directly
    instead of doing 12 independent nearest-neighbour distance checks.
    """
    norm_yaw = yaw_deg / yaw_range_deg if yaw_range_deg else 0.0
    norm_pitch = pitch_deg / pitch_range_deg if pitch_range_deg else 0.0
    theta_deg = math.degrees(math.atan2(norm_yaw, norm_pitch)) % 360.0
    index = round(theta_deg / 30.0) % 12
    clock_number = 12 if index == 0 else index
    return f"{clock_number:02d}"


# --- Landmark detection + solvePnP pose estimation (lazy heavy imports) ----

# Generic 3D face model (millimetre-scale, arbitrary but consistent origin
# at the nose tip) used for `cv2.solvePnP`. These are widely-published
# approximate anthropometric constants (not a trained/licensed model
# artifact — plain geometry), the same set commonly used for OpenCV
# head-pose-estimation tutorials.
_GENERIC_3D_FACE_MODEL = np.array(
    [
        [0.0, 0.0, 0.0],  # nose tip
        [0.0, -63.6, -12.5],  # chin
        [-43.3, 32.7, -26.0],  # left eye outer corner
        [43.3, 32.7, -26.0],  # right eye outer corner
        [-28.9, -28.9, -24.1],  # left mouth corner
        [28.9, -28.9, -24.1],  # right mouth corner
    ],
    dtype=np.float64,
)

# MediaPipe FaceMesh landmark indices for the 6 solvePnP points. The same
# eye-corner/mouth-corner points double as the 5-point alignment template
# (left/right eye, nose tip, left/right mouth corner — the standard
# ArcFace/AdaFace 5-point convention, see ai_training.embedding.alignment).
_MP_NOSE_TIP = 1
_MP_CHIN = 152
_MP_LEFT_EYE_OUTER = 33
_MP_RIGHT_EYE_OUTER = 263
_MP_LEFT_MOUTH = 61
_MP_RIGHT_MOUTH = 291


@dataclass(frozen=True)
class FaceDetection:
    """A single detected face's landmarks + bbox, in pixel coordinates."""

    nose_tip: tuple[float, float]
    chin: tuple[float, float]
    left_eye: tuple[float, float]
    right_eye: tuple[float, float]
    left_mouth: tuple[float, float]
    right_mouth: tuple[float, float]
    bbox_wh: tuple[float, float]

    def solve_pnp_landmarks(self) -> np.ndarray:
        """6-point subset, in the same order as `_GENERIC_3D_FACE_MODEL`."""
        return np.array(
            [
                self.nose_tip,
                self.chin,
                self.left_eye,
                self.right_eye,
                self.left_mouth,
                self.right_mouth,
            ],
            dtype=np.float64,
        )

    def alignment_landmarks_5pt(self) -> np.ndarray:
        """5-point subset for `ai_training.embedding.alignment.align_face`,
        in the standard ArcFace/AdaFace order: left eye, right eye, nose
        tip, left mouth corner, right mouth corner."""
        return np.array(
            [self.left_eye, self.right_eye, self.nose_tip, self.left_mouth, self.right_mouth],
            dtype=np.float64,
        )


def _require_mediapipe() -> Any:
    try:
        import mediapipe as mp
    except ImportError as exc:  # pragma: no cover - depends on extras
        raise RuntimeError(
            "Face landmark detection requires the 'ml' extra (uv sync --extra ml): mediapipe."
        ) from exc
    return mp


def _require_cv2() -> Any:
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - depends on extras
        raise RuntimeError(
            "Pose estimation requires the 'ml' extra (uv sync --extra ml): opencv-python-headless."
        ) from exc
    return cv2


def detect_face_and_landmarks(frame_bgr: np.ndarray) -> FaceDetection | None:
    """Detect the (single, largest) face in a BGR frame and return its
    landmarks in pixel coordinates, or `None` if no face is found.

    Uses MediaPipe's legacy `solutions.face_mesh` API, whose model asset is
    bundled inside the installed `mediapipe` package (no separate download
    at runtime) — see the `ml` extra rationale in pyproject.toml.
    """
    mp = _require_mediapipe()
    h, w = frame_bgr.shape[:2]
    with mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True,
        max_num_faces=1,
        refine_landmarks=False,
        min_detection_confidence=0.5,
    ) as face_mesh:
        rgb = frame_bgr[:, :, ::-1]  # BGR -> RGB, mediapipe convention
        result = face_mesh.process(rgb)
        if not result.multi_face_landmarks:
            return None
        landmarks = result.multi_face_landmarks[0].landmark

        def _px(idx: int) -> tuple[float, float]:
            lm = landmarks[idx]
            return (lm.x * w, lm.y * h)

        xs = [lm.x * w for lm in landmarks]
        ys = [lm.y * h for lm in landmarks]
        bbox_wh = (max(xs) - min(xs), max(ys) - min(ys))

        return FaceDetection(
            nose_tip=_px(_MP_NOSE_TIP),
            chin=_px(_MP_CHIN),
            left_eye=_px(_MP_LEFT_EYE_OUTER),
            right_eye=_px(_MP_RIGHT_EYE_OUTER),
            left_mouth=_px(_MP_LEFT_MOUTH),
            right_mouth=_px(_MP_RIGHT_MOUTH),
            bbox_wh=bbox_wh,
        )


def estimate_pose_from_landmarks(
    detection: FaceDetection, image_size: tuple[int, int]
) -> tuple[float, float, float]:
    """`cv2.solvePnP`-based (yaw, pitch, roll) in degrees, from 6 landmarks
    against the generic 3D face model. `image_size` is `(width, height)`.
    """
    cv2 = _require_cv2()
    width, height = image_size
    focal_length = float(width)
    center = (width / 2.0, height / 2.0)
    camera_matrix = np.array(
        [[focal_length, 0, center[0]], [0, focal_length, center[1]], [0, 0, 1]], dtype=np.float64
    )
    dist_coeffs = np.zeros((4, 1))

    ok, rotation_vec, _translation_vec = cv2.solvePnP(
        _GENERIC_3D_FACE_MODEL,
        detection.solve_pnp_landmarks(),
        camera_matrix,
        dist_coeffs,
        flags=cv2.SOLVEPNP_ITERATIVE,
    )
    if not ok:
        raise RuntimeError("solvePnP failed to converge")

    rotation_matrix, _ = cv2.Rodrigues(rotation_vec)
    # Standard extraction of Euler angles from a rotation matrix (yaw around
    # Y, pitch around X, roll around Z), matching the OpenCV head-pose
    # tutorial convention widely used for this exact setup.
    sy = math.sqrt(rotation_matrix[0, 0] ** 2 + rotation_matrix[1, 0] ** 2)
    singular = sy < 1e-6
    if not singular:
        pitch = math.atan2(rotation_matrix[2, 1], rotation_matrix[2, 2])
        yaw = math.atan2(-rotation_matrix[2, 0], sy)
        roll = math.atan2(rotation_matrix[1, 0], rotation_matrix[0, 0])
    else:  # pragma: no cover - degenerate near-gimbal-lock pose
        pitch = math.atan2(-rotation_matrix[1, 2], rotation_matrix[1, 1])
        yaw = math.atan2(-rotation_matrix[2, 0], sy)
        roll = 0.0
    return math.degrees(yaw), math.degrees(pitch), math.degrees(roll)
