"""`run_enrollment_qc_core`'s D-4.4 wiring (TSD-edge-cases.md D-4.4, REC 13,
EC-TR-04) against a fake DB cursor + monkeypatched heavy pipeline pieces --
never real Postgres/S3/cv2/mediapipe/dlib, same convention as
test_worker_task_synthetic_masked.py / test_gallery_reembed.py.

Only the QC_RUNNING happy path (through to ENROLLED) is exercised here,
since that's the only path that reaches the D-4.4 step at all -- mirrors
test_worker_task_synthetic_masked.py's own scoping note.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import ai_training.worker.tasks as tasks_module
from ai_training.config import Settings
from ai_training.embedding.embedder import StubEmbedder
from ai_training.quality.report import PositionResult, QCReport
from ai_training.worker.tasks import run_enrollment_qc_core


class FakeCursor:
    """Same shape as test_worker_task_synthetic_masked.py's FakeCursor --
    `fetchall()` always returns `[]`, which is exactly what
    `run_high_similarity_check_core`'s gallery/own-vector lookups need to
    see "no other identities enrolled yet" (the realistic single-session
    scenario these QC-pipeline tests exercise) rather than raising."""

    def __init__(self, *, state: str, user_id: str = "user-1") -> None:
        self.state = state
        self.user_id = user_id
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
        else:
            self._fetch_one = None

    def fetchone(self):
        return self._fetch_one

    def fetchall(self):
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


def _patch_qc_and_embedding(monkeypatch, *, frames_by_position: dict[str, Any]) -> None:
    monkeypatch.setattr(
        "ai_training.worker.tasks.run_quality_check",
        lambda video_bytes, *, session_id, settings, neutral_pose=None: (
            _pass_report(),
            frames_by_position,
        ),
    )

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


def test_enrollment_reaches_enrolled_with_no_other_gallery_identities(monkeypatch) -> None:
    """The ordinary case: this is the only enrolled identity so far --
    D-4.4's check runs (no exception) and finds nothing to flag."""
    frames_by_position = {"12": [MagicMock(position="12", blur=100.0, yaw=0.0, passed=True)]}
    _patch_qc_and_embedding(monkeypatch, frames_by_position=frames_by_position)

    cursor = FakeCursor(state="QC_RUNNING")
    outcome = run_enrollment_qc_core(cursor, _settings(), "session-1", downloader=_fake_downloader)

    assert outcome == "enrolled"
    assert cursor.state == "ENROLLED"


def test_high_similarity_check_failure_never_fails_enrollment(monkeypatch) -> None:
    """Acceptance criteria (D-4.4): the check must never block/fail
    enrollment. Simulate the check itself blowing up (e.g. a DB error on
    the recognition_configs write) and prove ENROLLED is still reached."""
    frames_by_position = {"12": [MagicMock(position="12", blur=100.0, yaw=0.0, passed=True)]}
    _patch_qc_and_embedding(monkeypatch, frames_by_position=frames_by_position)

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated recognition_configs write failure")

    monkeypatch.setattr(tasks_module, "run_high_similarity_check_core", _boom)

    cursor = FakeCursor(state="QC_RUNNING")
    outcome = run_enrollment_qc_core(cursor, _settings(), "session-1", downloader=_fake_downloader)

    assert outcome == "enrolled"
    assert cursor.state == "ENROLLED"

    # The enrollment's own final audit entry must still be present -- D-4.4
    # blowing up must not have unwound anything upstream of it.
    embedding_completed = [
        params
        for query, params in cursor.executed
        if query.startswith("INSERT INTO audit_logs")
        and params[2] == "enrollment.embedding_completed"
    ]
    assert len(embedding_completed) == 1
