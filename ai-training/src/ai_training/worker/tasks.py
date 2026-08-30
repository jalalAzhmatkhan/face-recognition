"""Celery tasks: real QC (TR-02) + embedding extraction (TR-03).

Registered under the exact task name backend dispatches
(`app.worker.tasks.run_enrollment_qc`) — see `celery_app.py` docstring for
why a second, name-matching task in a separate project is how this is
wired without either project importing the other.

**DB permission note** (see `config.DBSettings` docstring): this task reads
`enrollment_sessions`/`media_objects` and writes
`enrollment_sessions.state`/`qc_report`, `face_embeddings`, and
`audit_logs`, using a single `settings.db.dsn`. The two Postgres roles
`backend/README.md` documents (`ai_training_ro`, `ai_training_embeddings_write`)
do NOT currently cover the `enrollment_sessions`/`audit_logs` writes — that
gap is called out explicitly there and in this task's final report; it is
not silently papered over here.
"""

from __future__ import annotations

import logging
from typing import Any

from celery import Task

from ai_training.config import Settings, get_settings
from ai_training.db.audit_repo import insert_audit_log
from ai_training.db.connection import get_connection
from ai_training.db.embedding_repo import upsert_embeddings
from ai_training.db.enrollment_repo import (
    Cursor,
    get_latest_finalized_video,
    get_state,
    get_user_id,
    guarded_transition,
)
from ai_training.embedding.embedder import build_embedder
from ai_training.embedding.extractor import extract_gallery_embeddings
from ai_training.quality.pipeline import run_quality_check
from ai_training.worker.celery_app import celery_app

logger = logging.getLogger(__name__)

ACTOR = "system:ai-training-worker"

# Transient/retryable exceptions (DB connection drop, S3 blip, etc.) — kept
# broad-but-named rather than bare `Exception` so a genuine bug in this
# task's logic still surfaces as a real failure quickly instead of quietly
# retrying 5 times, mirroring backend/app/worker/tasks.py's choice.
RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
)


class DeadLetterTask(Task):
    """Local reimplementation of backend/app/worker/tasks.py's
    `DeadLetterTask` idiom (same `on_failure` -> one `audit_logs` row with
    `action="job.dead_letter"`), necessarily via raw SQL here since
    ai-training cannot import backend's `AuditLogRepository`/ORM session.
    """

    def on_failure(
        self,
        exc: BaseException,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: Any,
    ) -> None:
        super().on_failure(exc, task_id, args, kwargs, einfo)
        try:
            settings = get_settings()
            conn = get_connection(settings.db.dsn)
            try:
                with conn.cursor() as cursor:
                    insert_audit_log(
                        cursor,
                        actor=ACTOR,
                        action="job.dead_letter",
                        entity=f"task:{self.name}:{task_id}",
                        payload={
                            "task": self.name,
                            "task_id": task_id,
                            "args": [str(a) for a in args],
                            "kwargs": {k: str(v) for k, v in kwargs.items()},
                            "exception_type": type(exc).__name__,
                            "exception_message": str(exc),
                        },
                    )
                conn.commit()
            finally:
                conn.close()
        except Exception:  # noqa: BLE001 - dead-letter logging must never raise
            logger.exception(
                "ai_training.worker.dead_letter_write_failed task=%s task_id=%s", self.name, task_id
            )


def _default_download_video(bucket: str, key: str, settings: Settings) -> bytes:
    """Stream the enrollment video from S3 into memory. NFR-SEC-02: no
    disk persistence at THIS layer — `quality.pipeline.extract_frames`'s
    own short-lived temp file (documented there) is the one place video
    bytes ever touch a filesystem, and it deletes immediately.

    Builds the client from `settings.s3` (region/endpoint_url) rather than
    a bare `boto3.client("s3")` — found live: without threading
    `endpoint_url` through, this silently fell back to boto3's default AWS
    endpoint resolution instead of the configured MinIO/S3-compatible
    endpoint, resulting in a real-AWS `InvalidAccessKeyId` error against
    dev credentials instead of talking to the intended bucket.
    """
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - depends on extras
        raise RuntimeError(
            "S3 access requires the 'ml' extra (uv sync --extra ml): boto3."
        ) from exc
    client = boto3.client(
        "s3",
        region_name=settings.s3.region or None,
        endpoint_url=settings.s3.endpoint_url or None,
    )
    response = client.get_object(Bucket=bucket, Key=key)
    return response["Body"].read()


def run_enrollment_qc_core(
    cursor: Cursor,
    settings: Settings,
    session_id: str,
    *,
    downloader: Any = _default_download_video,
) -> str:
    """Core QC + embedding logic, DB-cursor-injected for unit testing
    without a Celery task context or a real Postgres connection (mirrors
    the `_run_enrollment_qc_stub`/`run_enrollment_qc` split in
    backend/app/worker/tasks.py). Returns a short outcome string purely so
    tests can assert on it.

    **Idempotency** (NFR-OPS-02): the very first thing this does is check
    the session's *current* state; anything other than `QC_RUNNING` is a
    no-op (audited, not silently dropped) — this is what makes a duplicate
    `run_enrollment_qc.delay(session_id)` dispatch (backend's qc_queue.py
    documents this can happen on broker hiccups) safe to run twice. Every
    subsequent state write goes through `guarded_transition`, which
    re-checks the expected state in its own `WHERE` clause, so even a
    concurrent duplicate delivery racing THIS run cannot double-apply a
    transition.
    """
    current_state = get_state(cursor, session_id)
    if current_state is None:
        insert_audit_log(
            cursor,
            actor=ACTOR,
            action="job.qc_skipped",
            entity=f"enrollment_session:{session_id}",
            payload={"reason": "session_not_found"},
        )
        return "skipped_not_found"

    if current_state != "QC_RUNNING":
        insert_audit_log(
            cursor,
            actor=ACTOR,
            action="job.qc_skipped",
            entity=f"enrollment_session:{session_id}",
            payload={"reason": "not_qc_running", "state": current_state},
        )
        return "skipped_wrong_state"

    media = get_latest_finalized_video(cursor, session_id)
    if media is None:
        rejected_report = {
            "session_id": session_id,
            "overall": "REJECTED_QUALITY",
            "coverage_ratio": 0.0,
            "positions": [],
            "reasons": ["video_missing"],
        }
        if guarded_transition(
            cursor,
            session_id,
            expected_state="QC_RUNNING",
            new_state="REJECTED_QUALITY",
            qc_report=rejected_report,
        ):
            insert_audit_log(
                cursor,
                actor=ACTOR,
                action="enrollment.qc_rejected",
                entity=f"enrollment_session:{session_id}",
                payload=rejected_report,
            )
            return "rejected_video_missing"
        insert_audit_log(
            cursor,
            actor=ACTOR,
            action="job.qc_skipped",
            entity=f"enrollment_session:{session_id}",
            payload={"reason": "race_lost_qc_running"},
        )
        return "skipped_race"

    bucket, key = media
    video_bytes = downloader(bucket, key, settings)
    try:
        report, frames_by_position = run_quality_check(
            video_bytes, session_id=session_id, settings=settings.qc
        )
    except RuntimeError:
        # A corrupt/undecodable video is a CONTENT quality problem, not a
        # worker fault -- retrying will never fix it. Found live: without
        # this, extract_frames's RuntimeError propagated as an unhandled
        # task failure, burning through every retry/backoff attempt before
        # landing in the dead-letter table for something that was always
        # going to fail the same way. Route it through the same
        # REJECTED_QUALITY path as "video_missing" instead.
        logger.warning(
            "ai_training.worker.video_undecodable session_id=%s bucket=%s key=%s",
            session_id,
            bucket,
            key,
        )
        rejected_report = {
            "session_id": session_id,
            "overall": "REJECTED_QUALITY",
            "coverage_ratio": 0.0,
            "positions": [],
            "reasons": ["video_undecodable"],
        }
        if guarded_transition(
            cursor,
            session_id,
            expected_state="QC_RUNNING",
            new_state="REJECTED_QUALITY",
            qc_report=rejected_report,
        ):
            insert_audit_log(
                cursor,
                actor=ACTOR,
                action="enrollment.qc_rejected",
                entity=f"enrollment_session:{session_id}",
                payload=rejected_report,
            )
            return "rejected_video_undecodable"
        insert_audit_log(
            cursor,
            actor=ACTOR,
            action="job.qc_skipped",
            entity=f"enrollment_session:{session_id}",
            payload={"reason": "race_lost_qc_running"},
        )
        return "skipped_race"
    qc_report_dict = report.model_dump(mode="json")

    if report.overall != "PASS":
        if guarded_transition(
            cursor,
            session_id,
            expected_state="QC_RUNNING",
            new_state="REJECTED_QUALITY",
            qc_report=qc_report_dict,
        ):
            insert_audit_log(
                cursor,
                actor=ACTOR,
                action="enrollment.qc_rejected",
                entity=f"enrollment_session:{session_id}",
                payload=qc_report_dict,
            )
            return "rejected_quality"
        insert_audit_log(
            cursor,
            actor=ACTOR,
            action="job.qc_skipped",
            entity=f"enrollment_session:{session_id}",
            payload={"reason": "race_lost_qc_running"},
        )
        return "skipped_race"

    if not guarded_transition(
        cursor,
        session_id,
        expected_state="QC_RUNNING",
        new_state="QC_PASSED",
        qc_report=qc_report_dict,
    ):
        insert_audit_log(
            cursor,
            actor=ACTOR,
            action="job.qc_skipped",
            entity=f"enrollment_session:{session_id}",
            payload={"reason": "race_lost_qc_running"},
        )
        return "skipped_race"
    insert_audit_log(
        cursor,
        actor=ACTOR,
        action="enrollment.qc_passed",
        entity=f"enrollment_session:{session_id}",
        payload=qc_report_dict,
    )

    # --- TR-03: embedding extraction, continuing within the same job run -
    if not guarded_transition(
        cursor, session_id, expected_state="QC_PASSED", new_state="EMBEDDING"
    ):
        insert_audit_log(
            cursor,
            actor=ACTOR,
            action="job.qc_skipped",
            entity=f"enrollment_session:{session_id}",
            payload={"reason": "race_lost_qc_passed"},
        )
        return "skipped_race"

    embedder = build_embedder(settings)
    templates = extract_gallery_embeddings(frames_by_position, embedder)

    user_id = get_user_id(cursor, session_id)
    if user_id is None:  # pragma: no cover - session existed moments ago; defensive only
        raise RuntimeError(f"enrollment_session {session_id} disappeared mid-job")

    inserted = upsert_embeddings(
        cursor,
        user_id=user_id,
        session_id=session_id,
        model_version=embedder.model_version,
        embeddings=templates,
    )

    if not guarded_transition(cursor, session_id, expected_state="EMBEDDING", new_state="ENROLLED"):
        insert_audit_log(
            cursor,
            actor=ACTOR,
            action="job.qc_skipped",
            entity=f"enrollment_session:{session_id}",
            payload={"reason": "race_lost_embedding"},
        )
        return "skipped_race"

    insert_audit_log(
        cursor,
        actor=ACTOR,
        action="enrollment.embedding_completed",
        entity=f"enrollment_session:{session_id}",
        payload={
            "pose_buckets": [t.pose_bucket for t in templates],
            "embeddings_written": inserted,
            "model_version": embedder.model_version,
        },
    )
    return "enrolled"


@celery_app.task(
    name="app.worker.tasks.run_enrollment_qc",
    base=DeadLetterTask,
    bind=True,
    autoretry_for=RETRYABLE_EXCEPTIONS,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
)
def run_enrollment_qc(self: Task, session_id: str) -> str:
    """Real QC (TR-02) + embedding-extraction (TR-03) pipeline for an
    enrollment session (FR-ENR-06/07). This is the task backend's
    `app/services/qc_queue.py` dispatches by name — see `celery_app.py`.
    """
    settings = get_settings()
    conn = get_connection(settings.db.dsn)
    try:
        with conn.cursor() as cursor:
            outcome = run_enrollment_qc_core(cursor, settings, session_id)
        conn.commit()
        return outcome
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
