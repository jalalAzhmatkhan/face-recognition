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

    def __init__(
        self,
        *,
        sessions: list[tuple[str, str]],
        already_embedded: set[str],
        sweep_photo_sessions: dict[str, list[tuple[int, str, str]]] | None = None,
    ) -> None:
        self.sessions = sessions
        self.already_embedded = already_embedded
        # session_id -> [(clock_position, bucket, key)]. Absent/empty means
        # "legacy video session", which is exactly the production signal.
        self.sweep_photo_sessions = sweep_photo_sessions or {}
        self.executed: list[tuple[str, tuple]] = []
        self._fetch_one: tuple | None = None
        self._fetch_all: list[tuple] = []

    def execute(self, query: str, params: tuple = ()) -> None:
        self.executed.append((query, params))
        # Reset BOTH buffers on every statement: leaving a stale _fetch_all
        # behind meant an unrecognised query silently handed back the
        # PREVIOUS query's rows (found live when get_sweep_photos was added
        # and fetchall() returned the session list, blowing up on int()).
        self._fetch_one = None
        self._fetch_all = []
        if query.startswith("SELECT id, user_id FROM enrollment_sessions"):
            self._fetch_all = list(self.sessions)
        elif query.startswith("SELECT 1 FROM face_embeddings"):
            session_id = params[0]
            self._fetch_one = (1,) if session_id in self.already_embedded else None
        elif query.startswith("SELECT clock_position, s3_bucket, s3_key FROM media_objects"):
            self._fetch_all = list(self.sweep_photo_sessions.get(params[0], []))
        elif query.startswith("SELECT s3_bucket, s3_key FROM media_objects"):
            session_id = params[0]
            self._fetch_one = ("frac-media", f"video/{session_id}.webm")
        elif query.startswith(("DELETE FROM face_embeddings", "INSERT INTO ")):
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
    monkeypatch.setattr(
        "ai_training.worker.tasks.run_photo_quality_check",
        lambda photos, *, session_id, settings, neutral_pose=None: (
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


def test_reembeds_a_photo_enrolled_session_from_its_sweep_frames(monkeypatch) -> None:
    """Without the photo branch a photo-enrolled session counts as
    `skipped_no_video` and silently keeps its OLD model's embeddings --
    i.e. it drops out of the gallery on the next model promotion, which
    looks exactly like the recognition regression a promotion is supposed
    to avoid."""
    _stub_frames_by_position(monkeypatch)
    monkeypatch.setattr(
        "ai_training.worker.tasks.build_embedder",
        lambda settings: StubEmbedder(version="adaface-v2"),
    )

    cursor = FakeCursor(
        sessions=[("session-photo", "user-1")],
        already_embedded=set(),
        sweep_photo_sessions={
            "session-photo": [(p, "frac-media", f"photo_pos_{p:02d}_1.jpg") for p in range(1, 13)]
        },
    )
    counts = run_gallery_reembed_job_core(
        cursor, _settings(), "adaface-v2", downloader=_fake_downloader
    )

    assert counts == {"processed": 1, "skipped_already_done": 0, "skipped_no_video": 0, "failed": 0}


def test_a_photo_session_never_reaches_the_video_lookup(monkeypatch) -> None:
    _stub_frames_by_position(monkeypatch)
    monkeypatch.setattr(
        "ai_training.worker.tasks.build_embedder",
        lambda settings: StubEmbedder(version="adaface-v2"),
    )

    cursor = FakeCursor(
        sessions=[("session-photo", "user-1")],
        already_embedded=set(),
        sweep_photo_sessions={"session-photo": [(1, "frac-media", "photo_pos_01_1.jpg")]},
    )
    run_gallery_reembed_job_core(cursor, _settings(), "adaface-v2", downloader=_fake_downloader)

    assert not [q for q, _p in cursor.executed if "kind = 'video'" in q]


def test_a_mixed_batch_routes_each_session_by_its_own_shape(monkeypatch) -> None:
    _stub_frames_by_position(monkeypatch)
    monkeypatch.setattr(
        "ai_training.worker.tasks.build_embedder",
        lambda settings: StubEmbedder(version="adaface-v2"),
    )

    cursor = FakeCursor(
        sessions=[("session-legacy", "user-1"), ("session-photo", "user-2")],
        already_embedded=set(),
        sweep_photo_sessions={"session-photo": [(1, "frac-media", "photo_pos_01_1.jpg")]},
    )
    counts = run_gallery_reembed_job_core(
        cursor, _settings(), "adaface-v2", downloader=_fake_downloader
    )

    assert counts["processed"] == 2
    video_lookups = [p for q, p in cursor.executed if "kind = 'video'" in q]
    assert video_lookups == [("session-legacy",)]


def test_proxy_task_in_backend_never_actually_runs() -> None:
    """Sanity check for the cross-service wiring decision: backend's own
    `run_gallery_reembed_job` (app/worker/tasks.py) is a name-only proxy
    that must never run for real."""
    assert tasks_module.run_gallery_reembed_job.name == "app.worker.tasks.run_gallery_reembed_job"
