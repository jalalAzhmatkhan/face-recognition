"""`run_gallery_reembed_job_core` (TR-08) against a fake DB cursor and
monkeypatched quality/embedding pipeline pieces — never real Postgres/S3/
torch/cv2, per project testing convention (mirrors
test_run_training_evaluation_job.py / test_worker_task_idempotency.py)."""

from unittest.mock import MagicMock

import ai_training.worker.tasks as tasks_module
from ai_training.config import Settings
from ai_training.embedding.embedder import StubEmbedder
from ai_training.worker.tasks import run_gallery_reembed_job_core


class FakeCursor:
    """Dispatches on query prefix, mirrors the FakeCursor idiom already
    established in test_worker_task_idempotency.py."""

    def __init__(self, *, sessions: list[tuple[str, str]], already_embedded: set[str]) -> None:
        self.sessions = sessions
        self.already_embedded = already_embedded
        self.executed: list[tuple[str, tuple]] = []
        self._fetch_one: tuple | None = None
        self._fetch_all: list[tuple] = []

    def execute(self, query: str, params: tuple = ()) -> None:
        self.executed.append((query, params))
        if query.startswith("SELECT id, user_id FROM enrollment_sessions"):
            self._fetch_all = list(self.sessions)
        elif query.startswith("SELECT 1 FROM face_embeddings"):
            session_id = params[0]
            self._fetch_one = (1,) if session_id in self.already_embedded else None
        elif query.startswith("SELECT s3_bucket, s3_key FROM media_objects"):
            session_id = params[0]
            self._fetch_one = ("frac-media", f"video/{session_id}.webm")
        elif query.startswith("DELETE FROM face_embeddings"):
            self._fetch_one = None
        elif query.startswith("INSERT INTO face_embeddings"):
            self._fetch_one = None
        elif query.startswith("INSERT INTO audit_logs"):
            self._fetch_one = None
        else:  # pragma: no cover - not exercised by these tests
            self._fetch_one = None

    def fetchone(self):
        return self._fetch_one

    def fetchall(self):
        return self._fetch_all


def _settings() -> Settings:
    return Settings(_env_file=None)


def _fake_downloader(bucket: str, key: str, settings: Settings) -> bytes:
    return b"fake-video-bytes"


def _stub_frames_by_position(monkeypatch) -> None:
    """Every session "decodes" to the same trivial frames_by_position -- the
    actual contents don't matter for these tests, only that
    extract_gallery_embeddings is monkeypatched to a deterministic fake so
    no real cv2/mediapipe pipeline runs."""
    monkeypatch.setattr(
        "ai_training.worker.tasks.run_quality_check",
        lambda video_bytes, *, session_id, settings, neutral_pose=None: (
            MagicMock(),
            {"12": ["frame"]},
        ),
    )

    class FakeTemplate:
        pose_bucket = "12"
        vector = [0.1] * 512
        model_version = "adaface-v2"

    monkeypatch.setattr(
        "ai_training.worker.tasks.extract_gallery_embeddings",
        lambda frames_by_position, embedder: [FakeTemplate()],
    )


def test_reembeds_every_enrolled_session_not_already_done(monkeypatch) -> None:
    _stub_frames_by_position(monkeypatch)
    monkeypatch.setattr(
        "ai_training.worker.tasks.build_embedder",
        lambda settings: StubEmbedder(version="adaface-v2"),
    )

    cursor = FakeCursor(
        sessions=[("session-1", "user-1"), ("session-2", "user-2")],
        already_embedded=set(),
    )
    counts = run_gallery_reembed_job_core(
        cursor, _settings(), "adaface-v2", downloader=_fake_downloader
    )

    assert counts == {"processed": 2, "skipped_already_done": 0, "skipped_no_video": 0, "failed": 0}
    insert_queries = [q for q, _ in cursor.executed if q.startswith("INSERT INTO face_embeddings")]
    assert len(insert_queries) == 2
    audit_actions = [
        params[2] for q, params in cursor.executed if q.startswith("INSERT INTO audit_logs")
    ]
    assert audit_actions == ["gallery.reembed_completed"]


def test_skips_session_already_embedded_under_this_model_version(monkeypatch) -> None:
    _stub_frames_by_position(monkeypatch)
    monkeypatch.setattr(
        "ai_training.worker.tasks.build_embedder",
        lambda settings: StubEmbedder(version="adaface-v2"),
    )

    cursor = FakeCursor(
        sessions=[("session-1", "user-1"), ("session-2", "user-2")],
        already_embedded={"session-1"},
    )
    counts = run_gallery_reembed_job_core(
        cursor, _settings(), "adaface-v2", downloader=_fake_downloader
    )

    assert counts == {"processed": 1, "skipped_already_done": 1, "skipped_no_video": 0, "failed": 0}


def test_skips_session_with_no_finalized_video(monkeypatch) -> None:
    _stub_frames_by_position(monkeypatch)
    monkeypatch.setattr(
        "ai_training.worker.tasks.build_embedder",
        lambda settings: StubEmbedder(version="adaface-v2"),
    )

    cursor = FakeCursor(sessions=[("session-1", "user-1")], already_embedded=set())

    def _no_video_downloader(bucket, key, settings):  # pragma: no cover - never called
        raise AssertionError("downloader should not be called when there is no video")

    # Force get_latest_finalized_video's underlying query to return nothing
    # for this one session by overriding the cursor's dispatch.
    original_execute = cursor.execute

    def _execute(query, params=()):
        if query.startswith("SELECT s3_bucket, s3_key FROM media_objects"):
            cursor._fetch_one = None
            cursor.executed.append((query, params))
            return
        original_execute(query, params)

    cursor.execute = _execute

    counts = run_gallery_reembed_job_core(
        cursor, _settings(), "adaface-v2", downloader=_no_video_downloader
    )
    assert counts == {"processed": 0, "skipped_already_done": 0, "skipped_no_video": 1, "failed": 0}


def test_one_session_failure_does_not_abort_the_batch(monkeypatch) -> None:
    _stub_frames_by_position(monkeypatch)
    monkeypatch.setattr(
        "ai_training.worker.tasks.build_embedder",
        lambda settings: StubEmbedder(version="adaface-v2"),
    )

    cursor = FakeCursor(
        sessions=[("session-fails", "user-1"), ("session-ok", "user-2")],
        already_embedded=set(),
    )

    def _flaky_downloader(bucket: str, key: str, settings: Settings) -> bytes:
        if "session-fails" in key:
            raise RuntimeError("S3 timeout")
        return b"fake-video-bytes"

    counts = run_gallery_reembed_job_core(
        cursor, _settings(), "adaface-v2", downloader=_flaky_downloader
    )

    assert counts == {"processed": 1, "skipped_already_done": 0, "skipped_no_video": 0, "failed": 1}


def test_never_deletes_embeddings_of_a_different_model_version(monkeypatch) -> None:
    """Blue/green-via-coexistence invariant (TR-08 task brief): the DELETE
    inside upsert_embeddings is always scoped to (session_id,
    model_version) -- re-embedding under a NEW version must never touch an
    OLD version's rows, since a rollback depends on them staying intact."""
    _stub_frames_by_position(monkeypatch)
    monkeypatch.setattr(
        "ai_training.worker.tasks.build_embedder",
        lambda settings: StubEmbedder(version="adaface-v2"),
    )

    cursor = FakeCursor(sessions=[("session-1", "user-1")], already_embedded=set())
    run_gallery_reembed_job_core(cursor, _settings(), "adaface-v2", downloader=_fake_downloader)

    delete_queries = [
        (q, p) for q, p in cursor.executed if q.startswith("DELETE FROM face_embeddings")
    ]
    assert len(delete_queries) == 1
    _query, params = delete_queries[0]
    assert params == ("session-1", "adaface-v2")


def test_proxy_task_in_backend_never_actually_runs() -> None:
    """Sanity check for the cross-service wiring decision: backend's own
    `run_gallery_reembed_job` (app/worker/tasks.py) is a name-only proxy
    that must never run for real."""
    assert tasks_module.run_gallery_reembed_job.name == "app.worker.tasks.run_gallery_reembed_job"
