"""`run_enrollment_qc_core` looks up the session's FRONTAL PHOTO, estimates
its pose, and passes that as the neutral baseline into `run_quality_check`
-- against a fake DB cursor + monkeypatched heavy pipeline pieces, never
real Postgres/S3/cv2/mediapipe.

Mirrors test_qc_settings_override_wiring.py's FakeCursor conventions, but
this cursor distinguishes the `kind = 'photo'` lookup from the
`kind = 'video'` one (both share a `SELECT s3_bucket, s3_key FROM
media_objects` prefix).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

from ai_training.config import Settings
from ai_training.embedding.embedder import StubEmbedder
from ai_training.quality.report import PositionResult, QCReport
from ai_training.worker.tasks import run_enrollment_qc_core

VIDEO_KEY = "enrollment/user-1/session-1/rotation.webm"
PHOTO_KEY = "enrollment/user-1/session-1/photo_1.jpg"


class FakeCursor:
    def __init__(self, *, state: str = "QC_RUNNING", has_photo: bool = True) -> None:
        self.state = state
        self.has_photo = has_photo
        self.executed: list[tuple[str, tuple]] = []
        self.rowcount = 0
        self._fetch_one: tuple | None = None

    def execute(self, query: str, params: tuple = ()) -> None:
        self.executed.append((query, params))
        if query.startswith("SELECT state FROM enrollment_sessions"):
            self._fetch_one = (self.state,)
        elif query.startswith("SELECT user_id FROM enrollment_sessions"):
            self._fetch_one = ("user-1",)
        elif "kind = 'photo'" in query:
            self._fetch_one = ("frac-media", PHOTO_KEY) if self.has_photo else None
        elif "kind = 'video'" in query:
            self._fetch_one = ("frac-media", VIDEO_KEY)
        elif query.startswith("SELECT value FROM system_parameters"):
            self._fetch_one = None
        elif query.startswith("UPDATE enrollment_sessions"):
            expected_state = params[-1]
            if expected_state == self.state:
                self.state = params[0]
                self.rowcount = 1
            else:  # pragma: no cover - not exercised by these tests
                self.rowcount = 0
            self._fetch_one = None
        else:
            self._fetch_one = None

    def fetchone(self):
        return self._fetch_one

    def fetchall(self):  # pragma: no cover - not needed by this path
        return []


def _settings() -> Settings:
    return Settings(_env_file=None)


def _downloader(bucket: str, key: str, settings: Settings) -> bytes:
    return b"photo-bytes" if key == PHOTO_KEY else b"video-bytes"


def _pass_report() -> QCReport:
    return QCReport(
        session_id="session-1",
        overall="PASS",
        coverage_ratio=1.0,
        positions=[PositionResult(position="12", passed=True, best_score=100.0)],
        generated_at=datetime.now(UTC),
    )


def _patch_pipeline(monkeypatch, captured: dict[str, Any]) -> None:
    def fake_run_quality_check(video_bytes, *, session_id, settings, neutral_pose=None):
        captured["video_bytes"] = video_bytes
        captured["neutral_pose"] = neutral_pose
        frames = {"12": [MagicMock(position="12", blur=100.0, yaw=0.0, passed=True)]}
        return _pass_report(), frames

    class FakeTemplate:
        pose_bucket = "12"
        vector = [0.1] * 512
        model_version = "stub-test"

    monkeypatch.setattr("ai_training.worker.tasks.run_quality_check", fake_run_quality_check)
    monkeypatch.setattr(
        "ai_training.worker.tasks.extract_gallery_embeddings",
        lambda frames_by_position, embedder: [FakeTemplate()],
    )
    monkeypatch.setattr(
        "ai_training.worker.tasks.build_embedder",
        lambda settings: StubEmbedder(version="stub-test"),
    )


def test_frontal_photo_pose_is_passed_as_the_neutral_baseline(monkeypatch) -> None:
    captured: dict[str, Any] = {}
    _patch_pipeline(monkeypatch, captured)
    seen: dict[str, Any] = {}

    def fake_estimate_neutral_pose(photo_bytes, settings):
        seen["photo_bytes"] = photo_bytes
        return (1.5, 24.3)

    monkeypatch.setattr(
        "ai_training.worker.tasks.estimate_neutral_pose", fake_estimate_neutral_pose
    )

    outcome = run_enrollment_qc_core(
        FakeCursor(), _settings(), "session-1", downloader=_downloader
    )

    assert outcome == "enrolled"
    # The baseline must come from the PHOTO, not the video.
    assert seen["photo_bytes"] == b"photo-bytes"
    assert captured["video_bytes"] == b"video-bytes"
    assert captured["neutral_pose"] == (1.5, 24.3)


def test_missing_frontal_photo_falls_back_to_no_calibration(monkeypatch) -> None:
    """A session with no FINALIZED photo must still run QC exactly as it did
    before calibration existed -- never fail because of it."""
    captured: dict[str, Any] = {}
    _patch_pipeline(monkeypatch, captured)

    def _must_not_run(photo_bytes, settings):  # pragma: no cover - asserted not called
        raise AssertionError("estimate_neutral_pose must not run without a frontal photo")

    monkeypatch.setattr("ai_training.worker.tasks.estimate_neutral_pose", _must_not_run)

    outcome = run_enrollment_qc_core(
        FakeCursor(has_photo=False), _settings(), "session-1", downloader=_downloader
    )

    assert outcome == "enrolled"
    assert captured["neutral_pose"] is None


def test_calibration_failure_never_blocks_enrollment(monkeypatch) -> None:
    """Pose estimation on the photo blowing up (undecodable image, missing
    `ml` extra, ...) degrades to uncalibrated QC, not a failed session."""
    captured: dict[str, Any] = {}
    _patch_pipeline(monkeypatch, captured)

    def _boom(photo_bytes, settings):
        raise RuntimeError("mediapipe unavailable")

    monkeypatch.setattr("ai_training.worker.tasks.estimate_neutral_pose", _boom)

    outcome = run_enrollment_qc_core(
        FakeCursor(), _settings(), "session-1", downloader=_downloader
    )

    assert outcome == "enrolled"
    assert captured["neutral_pose"] is None
