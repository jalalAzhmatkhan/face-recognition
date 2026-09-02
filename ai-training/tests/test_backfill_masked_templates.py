"""`run_backfill_masked_templates_job_core` (D-4.5, TSD-edge-cases.md D-4.5)
against a fake DB cursor and monkeypatched quality/embedding pipeline
pieces -- never real Postgres/S3/cv2/mediapipe/dlib, same convention as
test_gallery_reembed.py / test_worker_task_synthetic_masked.py.

This job is pure orchestration over EC-TR-02's already-tested
`generate_synthetic_masked_templates` (see test_synthetic_masked.py for
that function's own unit tests) -- these tests monkeypatch it to a
deterministic fake rather than re-testing mask-overlay/embedding logic
here.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import ai_training.worker.tasks as tasks_module
from ai_training.config import Settings
from ai_training.worker.tasks import (
    REENROLL_DUE_MARKED_ACTION,
    REENROLL_DUE_REASON_VIDEO_RETENTION_EXPIRED,
    run_backfill_masked_templates_job_core,
)


class FakeCursor:
    """Dispatches on query prefix, mirrors the FakeCursor idiom already
    established in test_gallery_reembed.py / test_worker_task_synthetic_masked.py.

    Stateful across calls to `execute` (and, deliberately, across more than
    one call to `run_backfill_masked_templates_job_core` against the SAME
    instance) so idempotency tests can prove a second run really does skip
    what the first run wrote -- `masked_by_user` starts as whatever the
    test seeds it with and grows every time an 8-param
    `INSERT INTO face_embeddings` (the synthetic_masked shape) is executed,
    exactly like a real `face_embeddings` table would.
    """

    def __init__(
        self,
        *,
        sessions: list[tuple[str, str]],
        media: dict[str, tuple[str, str, datetime | None] | None],
        already_masked: set[str] | None = None,
        already_reenroll_due: set[str] | None = None,
        sweep_photo_sessions: dict[str, list[tuple[int, str, str]]] | None = None,
    ) -> None:
        self.sessions = sessions
        self.media = media
        # session_id -> [(clock_position, bucket, key)]. Absent/empty means
        # "legacy video session", which is exactly the production signal.
        self.sweep_photo_sessions = sweep_photo_sessions or {}
        self.masked_by_user: set[str] = set(already_masked or set())
        self.reenroll_due_by_user: set[str] = set(already_reenroll_due or set())
        self.executed: list[tuple[str, tuple]] = []
        self.reenroll_due_calls: list[tuple[str, str]] = []
        self.audit_actions: list[tuple[str, dict]] = []
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
        elif query.startswith("SELECT clock_position, s3_bucket, s3_key FROM media_objects"):
            self._fetch_all = list(self.sweep_photo_sessions.get(params[0], []))
        elif query.startswith("SELECT 1 FROM face_embeddings WHERE user_id"):
            user_id = params[0]
            self._fetch_one = (1,) if user_id in self.masked_by_user else None
        elif query.startswith("SELECT s3_bucket, s3_key, retention_expires_at"):
            session_id = params[0]
            self._fetch_one = self.media.get(session_id)
        elif query.startswith("SELECT reenroll_due FROM users"):
            user_id = params[0]
            self._fetch_one = (user_id in self.reenroll_due_by_user,)
        elif query.startswith("UPDATE users SET reenroll_due"):
            reason, user_id = params
            self.reenroll_due_by_user.add(user_id)
            self.reenroll_due_calls.append((user_id, reason))
            self._fetch_one = None
        elif query.startswith(("DELETE FROM face_embeddings", "UPDATE training_jobs")):
            self._fetch_one = None
        elif query.startswith("INSERT INTO face_embeddings"):
            if len(params) == 8:
                user_id = params[1]
                self.masked_by_user.add(user_id)
            self._fetch_one = None
        elif query.startswith("INSERT INTO audit_logs"):
            import json

            action = params[2]
            payload = json.loads(params[4]) if params[4] is not None else None
            self.audit_actions.append((action, payload))
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


class _OneTemplateMaskProvider:
    """Fake `MaskOverlayProvider` -- proves the wiring without touching
    dlib/MaskTheFace, same role as test_worker_task_synthetic_masked.py's
    `_RecordingMaskProvider`."""

    def apply(self, frame_bgr, mask_type):
        return ("masked", frame_bgr, mask_type)


def _patch_pipeline(monkeypatch) -> None:
    """Deterministic stand-ins for the heavy per-frame pipeline pieces
    `generate_synthetic_masked_templates` calls internally, mirroring
    test_worker_task_synthetic_masked.py's patches."""
    monkeypatch.setattr(
        "ai_training.worker.tasks.run_quality_check",
        lambda video_bytes, *, session_id, settings, neutral_pose=None: (
            MagicMock(),
            {"12": [MagicMock(position="12", blur=100.0, yaw=0.0, passed=True)]},
        ),
    )
    monkeypatch.setattr(
        "ai_training.worker.tasks.run_photo_quality_check",
        lambda photos, *, session_id, settings, neutral_pose=None: (
            MagicMock(),
            {"12": [MagicMock(position="12", blur=100.0, yaw=0.0, passed=True)]},
        ),
    )
    monkeypatch.setattr(
        "ai_training.embedding.synthetic_masked.detect_face_and_landmarks",
        lambda frame: MagicMock(alignment_landmarks_5pt=lambda: [0.0]),
    )
    monkeypatch.setattr(
        "ai_training.embedding.synthetic_masked.align_face", lambda frame, landmarks: "aligned"
    )
    monkeypatch.setattr(
        "ai_training.worker.tasks.build_embedder",
        lambda settings: MagicMock(model_version="stub-test", embed=lambda aligned: [0.1] * 512),
    )


def _media_ok(session_id: str) -> tuple[str, str, None]:
    return ("frac-media", f"video/{session_id}.webm", None)


def test_backfills_every_enrolled_user_without_masked_templates(monkeypatch) -> None:
    _patch_pipeline(monkeypatch)
    sessions = [("session-1", "user-1"), ("session-2", "user-2")]
    cursor = FakeCursor(
        sessions=sessions,
        media={"session-1": _media_ok("session-1"), "session-2": _media_ok("session-2")},
    )

    counts = run_backfill_masked_templates_job_core(
        cursor,
        _settings(),
        "job-1",
        downloader=_fake_downloader,
        mask_overlay_provider=_OneTemplateMaskProvider(),
    )

    assert counts["processed"] == 2
    assert counts["templates_inserted"] == 2
    assert counts["skipped_already_has_masked"] == 0
    assert counts["skipped_media_retention_expired"] == 0
    assert counts["failed"] == 0

    synthetic_inserts = [
        params
        for query, params in cursor.executed
        if query.startswith("INSERT INTO face_embeddings") and len(params) == 8
    ]
    assert len(synthetic_inserts) == 2
    assert {p[-2:] for p in synthetic_inserts} == {(True, "synthetic_masked")}

    # mark_job_running, then mark_job_succeeded_without_run.
    job_updates = [p for q, p in cursor.executed if q.startswith("UPDATE training_jobs")]
    assert job_updates == [("job-1",), ("job-1",)]

    audit_actions = [
        params[2] for q, params in cursor.executed if q.startswith("INSERT INTO audit_logs")
    ]
    assert audit_actions == ["backfill_masked.job_running", "backfill_masked.job_completed"]


def test_skips_user_who_already_has_masked_templates(monkeypatch) -> None:
    """Idempotency (acceptance criteria): a user with an existing
    synthetic_masked template is skipped BEFORE any download happens."""
    _patch_pipeline(monkeypatch)
    sessions = [("session-1", "user-1"), ("session-2", "user-2")]

    def _downloader_must_not_see_user_1(bucket, key, settings):
        assert "session-1" not in key, "already-backfilled user must never be downloaded"
        return b"fake-video-bytes"

    cursor = FakeCursor(
        sessions=sessions,
        media={"session-1": _media_ok("session-1"), "session-2": _media_ok("session-2")},
        already_masked={"user-1"},
    )

    counts = run_backfill_masked_templates_job_core(
        cursor,
        _settings(),
        "job-1",
        downloader=_downloader_must_not_see_user_1,
        mask_overlay_provider=_OneTemplateMaskProvider(),
    )

    assert counts["skipped_already_has_masked"] == 1
    assert counts["processed"] == 1
    assert counts["templates_inserted"] == 1


def test_rerun_skips_users_the_first_run_already_backfilled(monkeypatch) -> None:
    """Full idempotency loop: run the job twice against the SAME (stateful)
    fake DB -- the second run must skip every user the first run
    successfully wrote a synthetic_masked template for, without
    downloading their video again."""
    _patch_pipeline(monkeypatch)
    sessions = [("session-1", "user-1"), ("session-2", "user-2")]
    cursor = FakeCursor(
        sessions=sessions,
        media={"session-1": _media_ok("session-1"), "session-2": _media_ok("session-2")},
    )

    first = run_backfill_masked_templates_job_core(
        cursor,
        _settings(),
        "job-1",
        downloader=_fake_downloader,
        mask_overlay_provider=_OneTemplateMaskProvider(),
    )
    assert first["processed"] == 2

    downloaded_keys: list[str] = []

    def _recording_downloader(bucket, key, settings):
        downloaded_keys.append(key)
        return b"fake-video-bytes"

    second = run_backfill_masked_templates_job_core(
        cursor,
        _settings(),
        "job-2",
        downloader=_recording_downloader,
        mask_overlay_provider=_OneTemplateMaskProvider(),
    )

    assert second["skipped_already_has_masked"] == 2
    assert second["processed"] == 0
    assert downloaded_keys == []


def test_skips_and_flags_reenroll_due_when_video_missing(monkeypatch) -> None:
    """Media past retention (D-4.5 acceptance criteria): a legacy ENROLLED
    session with no FINALIZED video row at all (purged, or never existed)
    is skipped -- never counted as `failed` -- and the user is flagged
    reenroll_due (A-5/EC-BE-05) rather than silently left gap-filled-never."""
    _patch_pipeline(monkeypatch)
    sessions = [("session-1", "user-1")]
    cursor = FakeCursor(sessions=sessions, media={"session-1": None})

    def _downloader_must_not_run(bucket, key, settings):  # pragma: no cover
        raise AssertionError("downloader must not be called when media is past retention")

    counts = run_backfill_masked_templates_job_core(
        cursor,
        _settings(),
        "job-1",
        downloader=_downloader_must_not_run,
        mask_overlay_provider=_OneTemplateMaskProvider(),
    )

    assert counts["skipped_media_retention_expired"] == 1
    assert counts["failed"] == 0
    assert cursor.reenroll_due_calls == [("user-1", REENROLL_DUE_REASON_VIDEO_RETENTION_EXPIRED)]
    reenroll_due_audit_entries = [
        (action, payload)
        for action, payload in cursor.audit_actions
        if action == REENROLL_DUE_MARKED_ACTION
    ]
    assert reenroll_due_audit_entries == [
        (
            REENROLL_DUE_MARKED_ACTION,
            {
                "user_id": "user-1",
                "reasons": [REENROLL_DUE_REASON_VIDEO_RETENTION_EXPIRED],
                "session_id": "session-1",
            },
        )
    ]


def test_skips_and_flags_reenroll_due_when_retention_already_expired_but_row_not_purged(
    monkeypatch,
) -> None:
    """The narrower race: BE-14's hourly purge job hasn't deleted the row
    yet, but `retention_expires_at` has already passed -- must be treated
    the same as "media gone", not downloaded."""
    _patch_pipeline(monkeypatch)
    sessions = [("session-1", "user-1")]
    expired_at = datetime.now(UTC) - timedelta(days=1)
    cursor = FakeCursor(
        sessions=sessions,
        media={"session-1": ("frac-media", "video/session-1.webm", expired_at)},
    )

    def _downloader_must_not_run(bucket, key, settings):  # pragma: no cover
        raise AssertionError("downloader must not be called for expired-but-not-yet-purged media")

    counts = run_backfill_masked_templates_job_core(
        cursor,
        _settings(),
        "job-1",
        downloader=_downloader_must_not_run,
        mask_overlay_provider=_OneTemplateMaskProvider(),
    )

    assert counts["skipped_media_retention_expired"] == 1
    assert cursor.reenroll_due_calls == [("user-1", REENROLL_DUE_REASON_VIDEO_RETENTION_EXPIRED)]


def test_reenroll_due_already_flagged_is_not_re_marked_or_double_audited(monkeypatch) -> None:
    """EC-BE-05's shared idempotency contract: a user someone else (its own
    age/score-based job, or an earlier run of THIS job) already flagged
    `reenroll_due=true` for must not be overwritten or re-audited -- "first
    to flag wins"."""
    _patch_pipeline(monkeypatch)
    sessions = [("session-1", "user-1")]
    cursor = FakeCursor(
        sessions=sessions,
        media={"session-1": None},
        already_reenroll_due={"user-1"},
    )

    counts = run_backfill_masked_templates_job_core(
        cursor,
        _settings(),
        "job-1",
        downloader=_fake_downloader,
        mask_overlay_provider=_OneTemplateMaskProvider(),
    )

    assert counts["skipped_media_retention_expired"] == 1
    # mark_user_reenroll_due's own UPDATE never ran (the SELECT short-circuited it).
    assert cursor.reenroll_due_calls == []
    assert [a for a, _ in cursor.audit_actions if a == REENROLL_DUE_MARKED_ACTION] == []


def test_one_session_failure_does_not_abort_the_batch(monkeypatch) -> None:
    """Per-session failure isolation (acceptance criteria)."""
    _patch_pipeline(monkeypatch)
    sessions = [("session-fails", "user-1"), ("session-ok", "user-2")]
    cursor = FakeCursor(
        sessions=sessions,
        media={
            "session-fails": _media_ok("session-fails"),
            "session-ok": _media_ok("session-ok"),
        },
    )

    def _flaky_downloader(bucket, key, settings):
        if "session-fails" in key:
            raise RuntimeError("S3 timeout")
        return b"fake-video-bytes"

    counts = run_backfill_masked_templates_job_core(
        cursor,
        _settings(),
        "job-1",
        downloader=_flaky_downloader,
        mask_overlay_provider=_OneTemplateMaskProvider(),
    )

    assert counts["failed"] == 1
    assert counts["processed"] == 1
    assert counts["templates_inserted"] == 1


def test_mask_overlay_unavailable_degrades_to_zero_templates_not_a_failure(monkeypatch) -> None:
    """Sandbox-honest scenario (task instructions): the real
    `MaskTheFaceProvider.apply()` always raises RuntimeError here (dlib not
    installable). A session must still count as `processed` with
    `templates_inserted` staying at 0 -- degrading gracefully exactly like
    EC-TR-02's per-enrollment path (test_worker_task_synthetic_masked.py's
    `test_mask_overlay_failure_does_not_fail_enrollment`), never as
    `failed`, and NEVER marked as "already has a masked template" on a
    later re-run since none was actually written."""
    _patch_pipeline(monkeypatch)

    class _AlwaysFailingMaskProvider:
        def apply(self, frame_bgr, mask_type):
            raise RuntimeError("dlib is not installed (simulated sandbox condition)")

    sessions = [("session-1", "user-1")]
    cursor = FakeCursor(sessions=sessions, media={"session-1": _media_ok("session-1")})

    counts = run_backfill_masked_templates_job_core(
        cursor,
        _settings(),
        "job-1",
        downloader=_fake_downloader,
        mask_overlay_provider=_AlwaysFailingMaskProvider(),
    )

    assert counts["processed"] == 1
    assert counts["templates_inserted"] == 0
    assert counts["failed"] == 0
    assert "user-1" not in cursor.masked_by_user


def test_scales_linearly_over_many_sessions(monkeypatch) -> None:
    """Not a real 5k-user load test (task-breakdown.md's throughput target
    is QA's job, see the core function's docstring) -- this only proves the
    per-session loop has no accidental O(n^2)/hanging behaviour by running
    a moderately large fake batch (mix of already-done, missing-video, and
    normal sessions) and asserting it completes quickly."""
    _patch_pipeline(monkeypatch)
    n = 100
    sessions = [(f"session-{i}", f"user-{i}") for i in range(n)]
    already_masked = {f"user-{i}" for i in range(0, n, 3)}  # every 3rd user already done
    media = {
        f"session-{i}": (None if i % 7 == 0 else _media_ok(f"session-{i}")) for i in range(n)
    }
    cursor = FakeCursor(sessions=sessions, media=media, already_masked=already_masked)

    started = time.monotonic()
    counts = run_backfill_masked_templates_job_core(
        cursor,
        _settings(),
        "job-1",
        downloader=_fake_downloader,
        mask_overlay_provider=_OneTemplateMaskProvider(),
    )
    elapsed = time.monotonic() - started

    assert elapsed < 5.0, "100 fake sessions must not take anywhere near this long"
    total = (
        counts["processed"]
        + counts["skipped_already_has_masked"]
        + counts["skipped_media_retention_expired"]
        + counts["failed"]
    )
    assert total == n
    assert counts["skipped_already_has_masked"] == len(already_masked)


def test_backfills_a_photo_enrolled_session_from_its_sweep_frames(monkeypatch) -> None:
    _patch_pipeline(monkeypatch)
    cursor = FakeCursor(
        sessions=[("session-photo", "user-1")],
        media={},
        sweep_photo_sessions={
            "session-photo": [(p, "frac-media", f"photo_pos_{p:02d}_1.jpg") for p in range(1, 13)]
        },
    )

    counts = run_backfill_masked_templates_job_core(
        cursor,
        _settings(),
        "job-1",
        downloader=_fake_downloader,
        mask_overlay_provider=_OneTemplateMaskProvider(),
    )

    assert counts["processed"] == 1
    assert counts["templates_inserted"] == 1


def test_a_photo_enrolled_session_is_never_flagged_reenroll_due(monkeypatch) -> None:
    """D-4.5's retention/reenroll_due branch exists for LEGACY users whose
    enrollment video may have aged out of the 90-day window (ASM-10). A
    session enrolled since the photo switch cannot be in that situation,
    so it must not be swept up by it -- flagging it would tell a
    perfectly-enrolled user to re-enrol for no reason."""
    _patch_pipeline(monkeypatch)
    cursor = FakeCursor(
        sessions=[("session-photo", "user-1")],
        # No video row at all: on the old code path this is precisely the
        # "media gone" case that flips reenroll_due.
        media={},
        sweep_photo_sessions={"session-photo": [(1, "frac-media", "photo_pos_01_1.jpg")]},
    )

    counts = run_backfill_masked_templates_job_core(
        cursor,
        _settings(),
        "job-1",
        downloader=_fake_downloader,
        mask_overlay_provider=_OneTemplateMaskProvider(),
    )

    assert counts["skipped_media_retention_expired"] == 0
    assert cursor.reenroll_due_calls == []
    assert "user.reenroll_due_marked" not in [action for action, _payload in cursor.audit_actions]


def test_a_legacy_session_with_expired_media_is_still_flagged(monkeypatch) -> None:
    """The other half of the same guard: adding the photo branch must not
    disarm D-4.5 for the legacy users it was built for."""
    _patch_pipeline(monkeypatch)
    cursor = FakeCursor(
        sessions=[("session-legacy", "user-1")],
        media={"session-legacy": None},
        sweep_photo_sessions={},
    )

    counts = run_backfill_masked_templates_job_core(
        cursor,
        _settings(),
        "job-1",
        downloader=_fake_downloader,
        mask_overlay_provider=_OneTemplateMaskProvider(),
    )

    assert counts["skipped_media_retention_expired"] == 1
    assert cursor.reenroll_due_calls == [("user-1", "video_retention_expired")]


def test_proxy_task_in_backend_never_actually_runs() -> None:
    """Sanity check for the cross-service wiring decision (mirrors
    test_gallery_reembed.py's identical check): backend's own
    `run_backfill_masked_templates_job` (app/worker/tasks.py) is a
    name-only proxy that must never run for real."""
    assert (
        tasks_module.run_backfill_masked_templates_job.name
        == "app.worker.tasks.run_backfill_masked_templates_job"
    )
