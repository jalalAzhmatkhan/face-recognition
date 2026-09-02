"""`run_enrollment_qc_core` picks the right capture shape.

Two shapes reach QC (FR-ENR-02): per-position sweep photos for sessions
captured since the switch, and a single `rotation.webm` for older ones.
Getting the CHOICE wrong is a silent, total failure — a photo session
routed down the video branch is rejected as `video_missing` even though
every frame it needs is sitting in S3 — so it gets its own tests.

Same FakeCursor conventions as test_neutral_pose_wiring.py; nothing here
touches real Postgres/S3/cv2.
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


def sweep_rows(count: int = 12) -> list[tuple[int, str, str]]:
    """`(clock_position, bucket, key)` exactly as psycopg hands them back —
    note clock_position is an INT here, not the "01".."12" string the QC
    pipeline uses; converting it is `get_sweep_photos`' job."""
    return [
        (position, "frac-media", f"enrollment/user-1/session-1/photo_pos_{position:02d}_1.jpg")
        for position in range(1, count + 1)
    ]


class FakeCursor:
    def __init__(
        self,
        *,
        state: str = "QC_RUNNING",
        sweep_photos: list[tuple[int, str, str]] | None = None,
        has_video: bool = True,
        has_frontal_photo: bool = True,
    ) -> None:
        self.state = state
        self.sweep_photos = sweep_photos or []
        self.has_video = has_video
        self.has_frontal_photo = has_frontal_photo
        self.executed: list[tuple[str, tuple]] = []
        self.qc_reports: list[str] = []
        self.rowcount = 0
        self._fetch_one: tuple | None = None
        self._fetch_all: list[tuple] = []

    def execute(self, query: str, params: tuple = ()) -> None:
        self.executed.append((query, params))
        self._fetch_one = None
        self._fetch_all = []
        if query.startswith("SELECT state FROM enrollment_sessions"):
            self._fetch_one = (self.state,)
        elif query.startswith("SELECT user_id FROM enrollment_sessions"):
            self._fetch_one = ("user-1",)
        elif query.startswith("SELECT clock_position, s3_bucket, s3_key FROM media_objects"):
            self._fetch_all = list(self.sweep_photos)
        elif "kind = 'photo'" in query:
            self._fetch_one = ("frac-media", PHOTO_KEY) if self.has_frontal_photo else None
        elif "kind = 'video'" in query:
            self._fetch_one = ("frac-media", VIDEO_KEY) if self.has_video else None
        elif query.startswith("UPDATE enrollment_sessions"):
            expected_state = params[-1]
            if expected_state == self.state:
                self.state = params[0]
                if len(params) == 4:
                    self.qc_reports.append(params[1])
                self.rowcount = 1
            else:  # pragma: no cover - not exercised by these tests
                self.rowcount = 0

    def fetchone(self):
        return self._fetch_one

    def fetchall(self):
        return self._fetch_all


def _settings() -> Settings:
    return Settings(_env_file=None)


def _downloader(bucket: str, key: str, settings: Settings) -> bytes:
    return f"bytes::{key}".encode()


def _pass_report() -> QCReport:
    return QCReport(
        session_id="session-1",
        overall="PASS",
        coverage_ratio=1.0,
        positions=[PositionResult(position="12", passed=True, best_score=100.0)],
        generated_at=datetime.now(UTC),
    )


def _patch_pipeline(monkeypatch) -> dict[str, Any]:
    """Record which QC entry point ran, and with what."""
    calls: dict[str, Any] = {"photo": None, "video": None}

    def fake_photo_qc(photos, *, session_id, settings, neutral_pose=None):
        calls["photo"] = {"photos": list(photos), "neutral_pose": neutral_pose}
        frames = {"12": [MagicMock(position="12", blur=100.0, yaw=0.0, passed=True)]}
        return _pass_report(), frames

    def fake_video_qc(video_bytes, *, session_id, settings, neutral_pose=None):
        calls["video"] = {"video_bytes": video_bytes, "neutral_pose": neutral_pose}
        frames = {"12": [MagicMock(position="12", blur=100.0, yaw=0.0, passed=True)]}
        return _pass_report(), frames

    class FakeTemplate:
        pose_bucket = "12"
        vector = [0.1] * 512
        model_version = "stub-test"

    monkeypatch.setattr("ai_training.worker.tasks.run_photo_quality_check", fake_photo_qc)
    monkeypatch.setattr("ai_training.worker.tasks.run_quality_check", fake_video_qc)
    monkeypatch.setattr("ai_training.worker.tasks.estimate_neutral_pose", lambda b, s: (0.0, 24.0))
    monkeypatch.setattr(
        "ai_training.worker.tasks.extract_gallery_embeddings",
        lambda frames_by_position, embedder: [FakeTemplate()],
    )
    monkeypatch.setattr(
        "ai_training.worker.tasks.build_embedder",
        lambda settings: StubEmbedder(version="stub-test"),
    )
    return calls


def test_a_session_with_sweep_photos_uses_the_photo_path(monkeypatch) -> None:
    calls = _patch_pipeline(monkeypatch)
    cursor = FakeCursor(sweep_photos=sweep_rows())

    outcome = run_enrollment_qc_core(cursor, _settings(), "session-1", downloader=_downloader)

    assert outcome == "enrolled"
    assert calls["video"] is None
    assert calls["photo"] is not None
    assert len(calls["photo"]["photos"]) == 12


def test_positions_reach_qc_as_zero_padded_strings_not_ints(monkeypatch) -> None:
    """The DB column is a smallint but the pipeline keys positions by
    "01".."12" (`quality.pose.CLOCK_POSITIONS`). Handing it a bare `5`
    would silently file every frame under an unknown key."""
    calls = _patch_pipeline(monkeypatch)
    cursor = FakeCursor(sweep_photos=sweep_rows())

    run_enrollment_qc_core(cursor, _settings(), "session-1", downloader=_downloader)

    positions = [position for position, _bytes in calls["photo"]["photos"]]
    assert positions == [f"{i:02d}" for i in range(1, 13)]


def test_each_sweep_frame_is_downloaded_by_its_own_key(monkeypatch) -> None:
    calls = _patch_pipeline(monkeypatch)
    cursor = FakeCursor(sweep_photos=sweep_rows(3))

    run_enrollment_qc_core(cursor, _settings(), "session-1", downloader=_downloader)

    assert [data for _position, data in calls["photo"]["photos"]] == [
        b"bytes::enrollment/user-1/session-1/photo_pos_01_1.jpg",
        b"bytes::enrollment/user-1/session-1/photo_pos_02_1.jpg",
        b"bytes::enrollment/user-1/session-1/photo_pos_03_1.jpg",
    ]


def test_photos_win_even_when_a_video_also_exists(monkeypatch) -> None:
    """The backend rejects mixed sessions at /complete, so this shouldn't
    occur -- but if a stray legacy video is ever present, the labelled
    photos are the better evidence and must be what QC judges."""
    calls = _patch_pipeline(monkeypatch)
    cursor = FakeCursor(sweep_photos=sweep_rows(), has_video=True)

    run_enrollment_qc_core(cursor, _settings(), "session-1", downloader=_downloader)

    assert calls["photo"] is not None
    assert calls["video"] is None


def test_a_legacy_session_with_no_sweep_photos_still_uses_the_video_path(monkeypatch) -> None:
    calls = _patch_pipeline(monkeypatch)
    cursor = FakeCursor(sweep_photos=[], has_video=True)

    outcome = run_enrollment_qc_core(cursor, _settings(), "session-1", downloader=_downloader)

    assert outcome == "enrolled"
    assert calls["photo"] is None
    assert calls["video"]["video_bytes"] == f"bytes::{VIDEO_KEY}".encode()


def test_neither_photos_nor_a_video_is_rejected_not_crashed(monkeypatch) -> None:
    _patch_pipeline(monkeypatch)
    cursor = FakeCursor(sweep_photos=[], has_video=False)

    outcome = run_enrollment_qc_core(cursor, _settings(), "session-1", downloader=_downloader)

    assert outcome == "rejected_video_missing"
    assert cursor.state == "REJECTED_QUALITY"
    assert "video_missing" in cursor.qc_reports[0]


def test_the_neutral_baseline_still_comes_from_the_frontal_photo(monkeypatch) -> None:
    """`get_frontal_photo` filters `clock_position IS NULL`, so the sweep
    frames -- which are the poses being MEASURED -- can never be picked as
    the baseline that measurement is relative to."""
    calls = _patch_pipeline(monkeypatch)
    cursor = FakeCursor(sweep_photos=sweep_rows())

    run_enrollment_qc_core(cursor, _settings(), "session-1", downloader=_downloader)

    assert calls["photo"]["neutral_pose"] == (0.0, 24.0)
    frontal_queries = [
        query for query, _params in cursor.executed if "clock_position IS NULL" in query
    ]
    assert len(frontal_queries) == 1


def test_a_photo_session_without_a_frontal_photo_runs_uncalibrated(monkeypatch) -> None:
    calls = _patch_pipeline(monkeypatch)
    cursor = FakeCursor(sweep_photos=sweep_rows(), has_frontal_photo=False)

    outcome = run_enrollment_qc_core(cursor, _settings(), "session-1", downloader=_downloader)

    assert outcome == "enrolled"
    assert calls["photo"]["neutral_pose"] is None
