"""`run_enrollment_qc_core`'s A-4 wiring (TSD-edge-cases.md A-4/OQ-1)
against a fake DB cursor + monkeypatched heavy pipeline pieces -- never
real Postgres/S3/cv2/mediapipe/dlib, same convention as
test_gallery_reembed.py / test_worker_task_idempotency.py.

Only the QC_RUNNING happy path (through to ENROLLED) is exercised here,
since that's the only path that reaches the A-4 step at all; the
short-circuit branches are already covered by test_worker_task_idempotency.py.
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
    """Dispatches on query prefix (mirrors test_gallery_reembed.py's
    FakeCursor), backed by a tiny in-memory `enrollment_sessions` row."""

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
            # Guarded transition: params are always (..., session_id, expected_state)
            # or (..., session_id) with expected_state last.
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


class _RecordingMaskProvider:
    """Fake `MaskOverlayProvider` (see mask_overlay.MaskOverlayProvider) --
    proves run_enrollment_qc_core wires frames_by_position/embedder into
    the A-4 pipeline correctly without any dlib/MaskTheFace involved."""

    def apply(self, frame_bgr, mask_type):
        return ("masked", frame_bgr, mask_type)


class _AlwaysFailingMaskProvider:
    def apply(self, frame_bgr, mask_type):
        raise RuntimeError("dlib is not installed (simulated sandbox condition)")


def test_enrolls_and_writes_synthetic_masked_templates(monkeypatch) -> None:
    frames_by_position = {"12": [MagicMock(position="12", blur=100.0, yaw=0.0, passed=True)]}
    _patch_qc_and_embedding(monkeypatch, frames_by_position=frames_by_position)
    monkeypatch.setattr(
        "ai_training.embedding.synthetic_masked.detect_face_and_landmarks",
        lambda frame: MagicMock(alignment_landmarks_5pt=lambda: [0.0]),
    )
    monkeypatch.setattr(
        "ai_training.embedding.synthetic_masked.align_face", lambda frame, landmarks: "aligned"
    )

    cursor = FakeCursor(state="QC_RUNNING")
    outcome = run_enrollment_qc_core(
        cursor,
        _settings(),
        "session-1",
        downloader=_fake_downloader,
        mask_overlay_provider=_RecordingMaskProvider(),
    )

    assert outcome == "enrolled"
    assert cursor.state == "ENROLLED"

    synthetic_inserts = [
        params
        for query, params in cursor.executed
        if query.startswith("INSERT INTO face_embeddings") and len(params) == 8
    ]
    assert len(synthetic_inserts) == 1
    # (id, user_id, session_id, model_version, pose_bucket, vector, masked, template_kind)
    assert synthetic_inserts[0][-2:] == (True, "synthetic_masked")

    ordinary_inserts = [
        params
        for query, params in cursor.executed
        if query.startswith("INSERT INTO face_embeddings") and len(params) == 6
    ]
    assert len(ordinary_inserts) == 1

    # qc_report on the FINAL (ENROLLED) transition must record the count.
    final_update_params = [
        params
        for query, params in cursor.executed
        if query.startswith("UPDATE enrollment_sessions") and "qc_report" in query
    ][-1]
    import json

    final_report = json.loads(final_update_params[1])
    assert final_report["synthetic_templates_generated"] == 1

    embedding_completed_payload = [
        params
        for query, params in cursor.executed
        if query.startswith("INSERT INTO audit_logs")
        and params[2] == "enrollment.embedding_completed"
    ][0]
    assert json.loads(embedding_completed_payload[4])["synthetic_templates_generated"] == 1


def test_mask_overlay_failure_does_not_fail_enrollment(monkeypatch) -> None:
    """The core A-4 resilience guarantee: if the mask-overlay provider is
    entirely unusable (e.g. MaskTheFaceProvider without dlib installed --
    this sandbox's actual current status, see
    ai_training.quality.mask_overlay's module docstring), enrollment still
    reaches ENROLLED with zero synthetic_masked templates, not a failure."""
    frames_by_position = {"12": [MagicMock(position="12", blur=100.0, yaw=0.0, passed=True)]}
    _patch_qc_and_embedding(monkeypatch, frames_by_position=frames_by_position)

    cursor = FakeCursor(state="QC_RUNNING")
    outcome = run_enrollment_qc_core(
        cursor,
        _settings(),
        "session-1",
        downloader=_fake_downloader,
        mask_overlay_provider=_AlwaysFailingMaskProvider(),
    )

    assert outcome == "enrolled"
    assert cursor.state == "ENROLLED"

    synthetic_inserts = [
        params
        for query, params in cursor.executed
        if query.startswith("INSERT INTO face_embeddings") and len(params) == 8
    ]
    assert synthetic_inserts == []

    import json

    final_update_params = [
        params
        for query, params in cursor.executed
        if query.startswith("UPDATE enrollment_sessions") and "qc_report" in query
    ][-1]
    final_report = json.loads(final_update_params[1])
    assert final_report["synthetic_templates_generated"] == 0
