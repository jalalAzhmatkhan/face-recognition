"""Frame extraction & pose binning stub (TR-02/TR-05).

Planned per ratified recommendation (SS4 of recommendations.md):
decode 360deg enrollment video in-memory -> SCRFD detect + 5 landmarks ->
yaw estimate -> pose bins {0, +-15 ... +-90} -> quality filter
(feature-norm + variance-of-Laplacian) -> top-K frames per bin.
"""

from __future__ import annotations

# Yaw pose bins (degrees); back-of-head frames are discarded (ASM-03).
POSE_BIN_YAWS: tuple[int, ...] = (-90, -75, -60, -45, -30, -15, 0, 15, 30, 45, 60, 75, 90)


def extract_frames(video_bytes: bytes, fps: float = 12.0) -> list[bytes]:
    """Decode video (held only in memory) and sample frames. TR-02."""
    raise NotImplementedError("Frame extraction lands with TR-02.")


def assign_pose_bin(yaw_degrees: float) -> int:
    """Map an estimated yaw to the nearest pose bin."""
    return min(POSE_BIN_YAWS, key=lambda b: abs(b - yaw_degrees))
