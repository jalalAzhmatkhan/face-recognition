"""Celery tasks: real QC (TR-02) + embedding extraction (TR-03) + synthetic
masked-template generation (A-4, TSD-edge-cases.md).

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
from ai_training.db.embedding_repo import (
    has_embeddings_for_model,
    upsert_embeddings,
    upsert_synthetic_masked_embeddings,
)
from ai_training.db.enrollment_repo import (
    Cursor,
    get_latest_finalized_video,
    get_state,
    get_user_id,
    guarded_transition,
    list_enrolled_sessions,
)
from ai_training.db.training_job_repo import (
    mark_job_failed,
    mark_job_running,
    mark_job_succeeded,
    upsert_model_metrics,
)
from ai_training.embedding.embedder import build_embedder
from ai_training.embedding.extractor import extract_gallery_embeddings
from ai_training.embedding.synthetic_masked import generate_synthetic_masked_templates
from ai_training.quality.mask_overlay import MaskOverlayProvider, build_mask_overlay_provider
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
    mask_overlay_provider: MaskOverlayProvider | None = None,
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

    `mask_overlay_provider` (A-4, TSD-edge-cases.md A-4/OQ-1) is injected
    the same way `downloader` is, defaulting to `None` -- which means "lazily
    build the real one via `build_mask_overlay_provider()` at the point of
    use" -- so importing this module never requires `dlib`/MaskTheFace, and
    tests can substitute a fake without touching either.
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

    # --- A-4 (TSD-edge-cases.md A-4/OQ-1): synthetic masked-template
    # generation, on top of the ordinary `enrolled` templates just written
    # above. Deliberately wrapped in its own try/except that swallows
    # EVERY exception: this whole feature must degrade to "0 synthetic
    # templates" rather than ever fail the enrollment itself (acceptance
    # criteria explicitly calls this out). `generate_synthetic_masked_templates`
    # already catches per-combination failures internally (see its own
    # docstring) -- this outer catch is the last-resort net for anything
    # unexpected in the selection/DB-write plumbing around it (e.g. a bug
    # in `select_masked_source_frames`, or a DB error in the upsert).
    synthetic_templates_generated = 0
    try:
        provider = (
            mask_overlay_provider
            if mask_overlay_provider is not None
            else build_mask_overlay_provider()
        )
        synthetic_templates = generate_synthetic_masked_templates(
            frames_by_position, embedder, provider, session_id=session_id
        )
        synthetic_templates_generated = upsert_synthetic_masked_embeddings(
            cursor,
            user_id=user_id,
            session_id=session_id,
            model_version=embedder.model_version,
            templates=synthetic_templates,
        )
    except Exception:  # noqa: BLE001 - A-4 must never fail enrollment, see comment above
        logger.exception(
            "ai_training.worker.synthetic_masked_templates_failed session_id=%s", session_id
        )
        synthetic_templates_generated = 0

    # Recorded on the FINAL qc_report (the one that lands on the ENROLLED
    # row) rather than the QC_PASSED-time report written earlier -- A-4
    # runs strictly after that write, so this is the only point where the
    # count is known. Acceptance criteria: "qc_report mencatat
    # synthetic_templates_generated".
    qc_report_dict["synthetic_templates_generated"] = synthetic_templates_generated

    if not guarded_transition(
        cursor,
        session_id,
        expected_state="EMBEDDING",
        new_state="ENROLLED",
        qc_report=qc_report_dict,
    ):
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
            "synthetic_templates_generated": synthetic_templates_generated,
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


# --- run_training_evaluation_job (BE-13, FR-TRN-02/03) ---------------------
#
# Registered under the exact task name backend's
# `app/services/training_queue.py` dispatches
# (`app.worker.tasks.run_training_evaluation_job`) — same cross-project
# wiring as `run_enrollment_qc` above (see `celery_app.py`'s module
# docstring). backend/app/worker/tasks.py ALSO registers a task under this
# same name, but only as a name-only proxy that always raises — see its
# docstring for why: unlike `run_enrollment_qc`'s BE-07-stub-then-TR-02
# history, there never was (and never will be) a legitimate backend-side
# implementation, since `evaluate_candidate` needs ML dependencies backend
# doesn't carry. THIS is the only implementation meant to actually run.
TRAINING_JOB_ACTOR = "system:ai-training-worker"


def run_training_evaluation_job_core(
    cursor: Cursor,
    settings: Settings,
    job_id: str,
    model_version: str,
    benchmark_id: str,
) -> str:
    """Core logic, DB-cursor-injected for unit testing without a Celery task
    context (same split as `run_enrollment_qc_core`). Returns a short
    outcome string (`"succeeded"` / `"failed"`) purely so tests can assert
    on it.

    No idempotency short-circuit on job status here (unlike
    `run_enrollment_qc_core`'s "already past QC_RUNNING" check) — a
    `training_jobs` row is created fresh per POST /training/jobs request and
    is not expected to receive duplicate `.delay()` dispatches the way an
    enrollment session's QC job can; a duplicate delivery would simply
    re-run the (expensive but side-effect-idempotent-at-the-DB-row-level)
    evaluation and overwrite the same job row with the same-shaped result.

    Never lets an `evaluate_candidate` exception propagate: this task is
    NOT registered with `autoretry_for` (retrying a failed evaluation run —
    e.g. a bad `benchmark_id`, a missing S3 object, a misconfigured embedder
    — will not fix it), so an uncaught exception here would otherwise go
    straight to `DeadLetterTask.on_failure` and leave `training_jobs.status`
    stuck at RUNNING forever. Catching it and writing FAILED explicitly is
    what makes `GET /training/jobs/{id}` observable either way.
    """
    mark_job_running(cursor, job_id)
    insert_audit_log(
        cursor,
        actor=TRAINING_JOB_ACTOR,
        action="training.job_running",
        entity=f"training_job:{job_id}",
        payload={"model_version": model_version, "benchmark_id": benchmark_id},
    )

    try:
        from ai_training.evaluation.metrics import evaluate_candidate

        report = evaluate_candidate(settings, model_version, benchmark_id)
    except Exception as exc:  # noqa: BLE001 - a failed evaluation is a normal outcome to record
        error_message = str(exc)
        mark_job_failed(cursor, job_id, error_message=error_message)
        insert_audit_log(
            cursor,
            actor=TRAINING_JOB_ACTOR,
            action="training.job_failed",
            entity=f"training_job:{job_id}",
            payload={
                "model_version": model_version,
                "benchmark_id": benchmark_id,
                "error": error_message,
            },
        )
        return "failed"

    upsert_model_metrics(
        cursor,
        version=model_version,
        mlflow_run_id=report.mlflow_run_id,
        recall=report.recall,
        f1=report.f1,
        precision=report.precision,
        latency_ms_p95=report.latency_ms_p95,
    )
    mark_job_succeeded(cursor, job_id, mlflow_run_id=report.mlflow_run_id)
    insert_audit_log(
        cursor,
        actor=TRAINING_JOB_ACTOR,
        action="training.job_succeeded",
        entity=f"training_job:{job_id}",
        payload={
            "model_version": model_version,
            "benchmark_id": benchmark_id,
            "recall": report.recall,
            "f1": report.f1,
            "precision": report.precision,
            "latency_ms_p95": report.latency_ms_p95,
            "mlflow_run_id": report.mlflow_run_id,
        },
    )
    return "succeeded"


@celery_app.task(
    name="app.worker.tasks.run_training_evaluation_job",
    base=DeadLetterTask,
    bind=True,
)
def run_training_evaluation_job(
    self: Task, job_id: str, model_version: str, benchmark_id: str
) -> str:
    """Real implementation (BE-13) of the training-evaluation job backend's
    `app/services/training_queue.py` dispatches by name. Runs
    `ai_training.evaluation.metrics.evaluate_candidate` (TR-07) and writes
    the outcome back to `training_jobs` + `models` — see
    `run_training_evaluation_job_core` for the full logic.

    Deliberately NOT given `autoretry_for`: see
    `run_training_evaluation_job_core`'s docstring for why retrying a failed
    evaluation is not the right default here (unlike `run_enrollment_qc`,
    whose retryable exceptions are transient infra blips, not evaluation
    failures).
    """
    settings = get_settings()
    conn = get_connection(settings.db.dsn)
    try:
        with conn.cursor() as cursor:
            outcome = run_training_evaluation_job_core(
                cursor, settings, job_id, model_version, benchmark_id
            )
        conn.commit()
        return outcome
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


GALLERY_REEMBED_ACTOR = "system:ai-training-worker"


def run_gallery_reembed_job_core(
    cursor: Cursor,
    settings: Settings,
    model_version: str,
    *,
    downloader: Any = _default_download_video,
) -> dict[str, int]:
    """TR-08 core logic: re-extract gallery embeddings for every ENROLLED
    session under `model_version`, DB-cursor-injected for unit testing
    (same split as `run_enrollment_qc_core`/`run_training_evaluation_job_core`).

    **Blue/green via coexistence, not a flag** (see module/task docstring
    below for the full rationale): this NEVER deletes an existing session's
    embeddings for any OTHER model_version — `embedding_repo.upsert_embeddings`
    only ever touches rows matching `(session_id, model_version)`. A
    promoted-then-rolled-back model therefore always has a fully intact
    gallery to roll back to, with no separate "restore" step.

    **Idempotent**: `has_embeddings_for_model` skips a session that was
    already re-embedded under this exact `model_version` (a retried/resumed
    job, or the same model promoted twice, does not redo the work).

    **Per-session failure isolation**: one session's video being missing,
    undecodable, or briefly unreachable in S3 does not abort the whole
    batch — it's counted as failed/skipped and the job moves on, mirroring
    `retention_service.purge_expired_media`'s per-item try/except.

    Returns counts (`processed`, `skipped_already_done`, `skipped_no_video`,
    `failed`) for the audit log entry / Celery task result — there is no
    dedicated job-status table for this yet (unlike `training_jobs` for
    BE-13); see the Celery task's docstring for why that is an accepted
    scope cut for TR-08's first version.
    """
    embedder = build_embedder(settings)
    counts = {"processed": 0, "skipped_already_done": 0, "skipped_no_video": 0, "failed": 0}

    for session_id, user_id in list_enrolled_sessions(cursor):
        try:
            if has_embeddings_for_model(cursor, session_id=session_id, model_version=model_version):
                counts["skipped_already_done"] += 1
                continue

            media = get_latest_finalized_video(cursor, session_id)
            if media is None:
                counts["skipped_no_video"] += 1
                continue
            bucket, key = media
            video_bytes = downloader(bucket, key, settings)

            try:
                _report, frames_by_position = run_quality_check(
                    video_bytes, session_id=session_id, settings=settings.qc
                )
            except RuntimeError:
                # Same "content problem, not a worker fault" classification
                # as run_enrollment_qc_core's identical guard -- the video
                # already passed QC once at enrollment time, so a decode
                # failure here means the stored object itself is now bad
                # (corrupted/replaced), not something a retry fixes.
                logger.warning(
                    "ai_training.worker.gallery_reembed_video_undecodable "
                    "session_id=%s bucket=%s key=%s",
                    session_id,
                    bucket,
                    key,
                )
                counts["failed"] += 1
                continue

            templates = extract_gallery_embeddings(frames_by_position, embedder)
            upsert_embeddings(
                cursor,
                user_id=user_id,
                session_id=session_id,
                model_version=embedder.model_version,
                embeddings=templates,
            )
            counts["processed"] += 1
        except Exception:  # noqa: BLE001 - one session must never sink the whole batch
            logger.exception(
                "ai_training.worker.gallery_reembed_session_failed session_id=%s", session_id
            )
            counts["failed"] += 1

    insert_audit_log(
        cursor,
        actor=GALLERY_REEMBED_ACTOR,
        action="gallery.reembed_completed",
        entity=f"model:{model_version}",
        payload={"model_version": model_version, **counts},
    )
    return counts


@celery_app.task(
    name="app.worker.tasks.run_gallery_reembed_job",
    base=DeadLetterTask,
    bind=True,
)
def run_gallery_reembed_job(self: Task, model_version: str) -> dict[str, int]:
    """FR-TRN-06: re-extract every ENROLLED session's gallery embeddings
    under the just-promoted `model_version`. Dispatched by backend's
    `app/services/gallery_queue.py` right after a successful
    `POST /models/{version}/promote` (BE-13/TR-08), registered under the
    identical task name — see `run_training_evaluation_job`'s docstring for
    why backend's own copy of that name must never actually execute.

    **Embedder note (same limitation as TR-03/TR-07)**: this uses whatever
    embedder `build_embedder(settings)` resolves to from THIS worker's own
    configuration (`TRN_EMBEDDER__BACKEND`/`TRN_EMBEDDER__ADAFACE_ARCH`) --
    there is no dynamic per-model-version weight-loading registry anywhere
    in this codebase yet. Operationally, whoever promotes a new model
    version must first point the ai-training worker's config at that
    model's weights; `model_version` here is used to LABEL the resulting
    `face_embeddings` rows (and to look them up for the idempotency check),
    not to select which weights get loaded.

    **"Atomic switch" / "no mixed-version matching" (FR-TRN-06) note**:
    this job does not need a separate "activate gallery version" step or an
    `is_active` flag anywhere. `face_embeddings.model_version` already
    exists as an indexed column (BE-02) -- once IN-07 (ai-inference's
    model+gallery switch, not yet built) queries the gallery filtered by
    the CURRENT PRODUCTION `models.version`, matching against a stale
    model's embeddings becomes structurally impossible: the query itself
    only ever sees rows tagged with the version it asks for. This job's
    entire job is to make sure that query returns a POPULATED result the
    moment a new version goes to PRODUCTION.

    **No job-status table / progress API for this** (accepted scope cut):
    unlike BE-13's `training_jobs`, there is nothing yet exposing "is the
    gallery re-embed for version X done?" via HTTP -- progress is only
    observable via the `gallery.reembed_completed` audit log entry (with
    per-outcome counts) this task's core function writes. A dedicated
    status API is a reasonable follow-up if this needs to be surfaced in
    FE-09/S-52's promotion flow, same spirit as the BE-15 follow-up FE-09
    itself produced.

    **Scale target (task-breakdown.md: "≤ 5k user selesai dalam menit")**:
    not load-tested here -- there is no 5k-real-enrollment dataset in this
    environment to test against. Functional correctness is verified live
    and by unit test; validating the throughput target at that scale is
    QA-08's (load testing) job, not this task's.
    """
    settings = get_settings()
    conn = get_connection(settings.db.dsn)
    try:
        with conn.cursor() as cursor:
            counts = run_gallery_reembed_job_core(cursor, settings, model_version)
        conn.commit()
        return counts
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
