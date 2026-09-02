"""`run_enrollment_qc_core` resolves the System Parameter admin-menu
enrollment-quality override (if any) and passes the EFFECTIVE `QCSettings`
into `run_quality_check` -- against a fake DB cursor + monkeypatched heavy
pipeline pieces, never real Postgres/S3/cv2/mediapipe. Mirrors
test_worker_task_synthetic_masked.py's FakeCursor/downloader conventions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

from ai_training.config import Settings
from ai_training.embedding.embedder import StubEmbedder
from ai_training.quality.report import PositionResult, QCReport
from ai_training.worker.tasks import run_enrollment_qc_core


class FakeCursor:
    def __init__(
        self, *, state: str, system_parameters_row: dict | None = None, user_id: str = "user-1"
    ) -> None:
        self.state = state
        self.user_id = user_id
        self._system_parameters_row = system_parameters_row
        self.executed: list[tuple[str, tuple]] = []
        self.rowcount = 0
        self._fetch_one: tuple | None = None

    def execute(self, query: str, params: tuple = ()) -> None:
        self.executed.append((query, params))
        if query.startswith("SELECT state FROM enrollment_sessions"):
            self._fetch_one = (self.state,)
        elif query.startswith("SELECT user_id FROM enrollment_sessions"):
            self._fetch_one = (self.user_id,)
        elif query.startswith("SELECT s3_bucket, s3_key FROM media_objects"):
            self._fetch_one = ("frac-media", "enrollment/user-1/session-1/rotation.webm")
        elif query.startswith("SELECT value FROM system_parameters"):
            self._fetch_one = (
                (self._system_parameters_row,) if self._system_parameters_row is not None else None
            )
        elif query.startswith("UPDATE enrollment_sessions"):
            expected_state = params[-1]
            if expected_state == self.state:
                self.state = params[0]
                self.rowcount = 1
            else:  # pragma: no cover - not exercised by these tests
                self.rowcount = 0
            self._fetch_one = None
        elif query.startswith(("DELETE FROM face_embeddings", "INSERT INTO face_embeddings")):
            self._fetch_one = None
        elif query.startswith("INSERT INTO audit_logs"):
            self._fetch_one = None
        else:  # pragma: no cover - not exercised by these tests
            self._fetch_one = None

    def fetchone(self):
        return self._fetch_one

    def fetchall(self):  # pragma: no cover - not needed by this path
        return []


def _settings() -> Settings:
    return Settings(_env_file=None)


def _fake_downloader(bucket: str, key: str, settings: Settings) -> bytes:
    return b"fake-video-bytes"


def _pass_report() -> QCReport:
    return QCReport(
        session_id="session-1",
        overall="PASS",
        coverage_ratio=1.0,
        positions=[PositionResult(position="12", passed=True, best_score=100.0)],
        generated_at=datetime.now(UTC),
    )


def _patch_embedding(monkeypatch) -> None:
    class FakeTemplate:
        pose_bucket = "12"
        vector = [0.1] * 512
        model_version = "stub-test"

    monkeypatch.setattr(
        "ai_training.worker.tasks.extract_gallery_embeddings",
        lambda frames_by_position, embedder: [FakeTemplate()],
    )
    monkeypatch.setattr(
        "ai_training.worker.tasks.build_embedder",
        lambda settings: StubEmbedder(version="stub-test"),
    )


def test_no_system_parameters_row_passes_settings_qc_unchanged(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_run_quality_check(video_bytes, *, session_id, settings, neutral_pose=None):
        captured["settings"] = settings
        frames = {"12": [MagicMock(position="12", blur=100.0, yaw=0.0, passed=True)]}
        return _pass_report(), frames

    monkeypatch.setattr("ai_training.worker.tasks.run_quality_check", fake_run_quality_check)
    _patch_embedding(monkeypatch)

    settings = _settings()
    cursor = FakeCursor(state="QC_RUNNING", system_parameters_row=None)
    outcome = run_enrollment_qc_core(
        cursor, settings, "session-1", downloader=_fake_downloader
    )

    assert outcome == "enrolled"
    assert captured["settings"] == settings.qc
    assert captured["settings"].blur_variance_min == settings.qc.blur_variance_min


def test_system_parameters_override_reaches_run_quality_check(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_run_quality_check(video_bytes, *, session_id, settings, neutral_pose=None):
        captured["settings"] = settings
        frames = {"12": [MagicMock(position="12", blur=100.0, yaw=0.0, passed=True)]}
        return _pass_report(), frames

    monkeypatch.setattr("ai_training.worker.tasks.run_quality_check", fake_run_quality_check)
    _patch_embedding(monkeypatch)

    settings = _settings()
    override = {"min_blur_variance": 30.0, "min_brightness": 35.0, "max_brightness": 225.0}
    cursor = FakeCursor(state="QC_RUNNING", system_parameters_row=override)
    outcome = run_enrollment_qc_core(
        cursor, settings, "session-1", downloader=_fake_downloader
    )

    assert outcome == "enrolled"
    resolved = captured["settings"]
    assert resolved.blur_variance_min == 30.0
    assert resolved.brightness_min == 35.0
    assert resolved.brightness_max == 225.0
    # System-parameters query must have actually been issued on the SAME
    # cursor the rest of the task runs on -- not a side-channel connection.
    assert any(
        query.startswith("SELECT value FROM system_parameters")
        for query, _params in cursor.executed
    )
