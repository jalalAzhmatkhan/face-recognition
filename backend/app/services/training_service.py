"""Training-job trigger + model promotion business logic (BE-13, TSD §7,
FR-TRN-02/05/06).

Layering per app/main.py docstring: routers (HTTP) -> services (business
logic) -> repositories (data access). This module owns:
  - creating a `training_jobs` row + dispatching the Celery evaluation job
    (`create_training_job`),
  - the FR-TRN-05 promotion gate (`promote_model`): CANDIDATE-only,
    no-recall-regression-vs-current-PRODUCTION, latency budget, and explicit
    human confirmation — all four are checked and reported together (not
    fail-fast on the first one) so a caller gets the full picture in one
    422/409 round-trip instead of fixing issues one at a time.

FR-TRN-06 (re-extract gallery embeddings with the newly-promoted model) is
explicitly OUT OF SCOPE here — that is TR-08 (ai-training), a follow-up
after promotion. `promote_model` does not trigger, queue, or stub anything
for it.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from app.core.config import Settings
from app.models.enums import ModelStage, TrainingJobStatus, TrainingJobType
from app.models.model_registry import ModelVersion
from app.models.training_job import TrainingJob
from app.repositories.audit_logs import AuditLogRepository
from app.repositories.model_versions import ModelVersionRepository
from app.repositories.training_jobs import TrainingJobRepository
from app.services import gallery_queue, training_queue


class TrainingJobNotFoundError(Exception):
    """No `training_jobs` row exists with the given id."""


class ModelVersionNotFoundError(Exception):
    """No `models` row exists with the given version."""


class PromotionGateError(Exception):
    """One or more FR-TRN-05 promotion gates failed.

    `reasons` is a list of human-readable, SPECIFIC rejection messages (not
    a single generic string) — the router maps this to a 409 with all of
    them in `detail`.
    """

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = reasons
        super().__init__("; ".join(reasons))


class ConfirmationRequiredError(Exception):
    """`ModelPromoteRequest.confirm` was not explicitly `true` (FR-TRN-05:
    promotion is human-in-the-loop, never triggered by an empty/default
    request body)."""


def create_training_job(
    job_repo: TrainingJobRepository,
    audit_repo: AuditLogRepository,
    *,
    job_type: TrainingJobType = TrainingJobType.EVALUATION,
    model_version: str | None = None,
    benchmark_id: str | None = None,
    snapshot_id: str | None = None,
    params: dict[str, Any] | None = None,
    actor: uuid.UUID,
) -> TrainingJob:
    """Create a `training_jobs` row (EC-BE-03: `job_type`/`snapshot_id`/
    `params` — see TrainingJobCreateRequest for the per-type required-field
    validation that already ran before this is called).

    Celery dispatch only happens for `EVALUATION` today
    (`run_training_evaluation_job`) — UNCHANGED from pre-EC-BE-03 behaviour.
    The other four job types persist a validated row but do not dispatch
    anything yet: `FINETUNE_EMBEDDER`/`FINETUNE_LIVENESS`/
    `BACKFILL_MASKED_TEMPLATES` have no Celery task implemented at all
    (B-2/B-3/D-4.5 are separate follow-up tasks), and `GALLERY_REEMBED` is
    already dispatched elsewhere as a side effect of `promote_model`
    (`gallery_queue.enqueue_gallery_reembed`) — wiring a *second*,
    independent dispatch path for it here is out of scope for this task
    (B-1 is schema + validation only, per the task brief).
    """
    job = TrainingJob(
        job_type=job_type,
        model_version=model_version,
        benchmark_id=benchmark_id,
        snapshot_id=snapshot_id,
        params=params,
        status=TrainingJobStatus.PENDING,
        triggered_by=actor,
    )
    job = job_repo.create(job)

    audit_repo.record(
        actor=str(actor),
        action="training.job_created",
        entity=f"training_job:{job.id}",
        payload={
            "job_type": job_type.value,
            "model_version": model_version,
            "benchmark_id": benchmark_id,
            "snapshot_id": snapshot_id,
            "params": params,
        },
    )

    if job_type == TrainingJobType.EVALUATION:
        training_queue.enqueue_training_job(job.id, model_version, benchmark_id)

    return job


def get_training_job(job_repo: TrainingJobRepository, job_id: uuid.UUID) -> TrainingJob:
    job = job_repo.get(job_id)
    if job is None:
        raise TrainingJobNotFoundError(str(job_id))
    return job


def list_training_jobs(
    job_repo: TrainingJobRepository,
    *,
    status: TrainingJobStatus | None = None,
    model_version: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[TrainingJob], int]:
    """BE-15: server-side history, replacing FE-09's localStorage-only
    workaround (see task-breakdown.md BE-15 note)."""
    jobs = job_repo.list(status=status, model_version=model_version, limit=limit, offset=offset)
    total = job_repo.count(status=status, model_version=model_version)
    return jobs, total


def list_models(
    model_repo: ModelVersionRepository, *, stage: ModelStage | None = None
) -> list[ModelVersion]:
    return model_repo.list(stage=stage)


def get_model(model_repo: ModelVersionRepository, version: str) -> ModelVersion:
    model = model_repo.get(version)
    if model is None:
        raise ModelVersionNotFoundError(version)
    return model


def promote_model(
    model_repo: ModelVersionRepository,
    audit_repo: AuditLogRepository,
    settings: Settings,
    *,
    version: str,
    confirm: bool,
    actor: uuid.UUID,
) -> ModelVersion:
    """FR-TRN-05: promote `version` from CANDIDATE to PRODUCTION.

    Gates (checked together, all reasons reported at once):
      1. `confirm` must be explicitly `true`.
      2. The model must exist and be in stage CANDIDATE.
      3. `recall >= current_production.recall` — skipped if there is no
         current PRODUCTION model at all (this is the first-ever
         promotion; there is no baseline to regress against).
      4. `latency_ms_p95 <= settings.promotion_latency_budget_ms` (NFR-PRF-01).
      5. EC-QA-01: `slice_gate_report["passes"]` must not be `False` — the
         per-slice no-regression-bertoleransi-CI gate
         (`ai_training.evaluation.regression_gate.evaluate_slice_regression_gate`)
         computed and persisted by the ai-training worker
         (`ai_training.db.training_job_repo.upsert_model_slice_gate_report`)
         onto `models.slice_gate_report`. This can reject a candidate that
         passes gate 3 (overall Recall) but regresses badly on one critical
         condition (masked-riil/dark/low-res/hijab/per-demografi-utama) that
         is a small slice of the overall benchmark. `slice_gate_report is
         None` (no report computed for this candidate yet — e.g. evaluated
         before EC-QA-01 shipped, or the harness has no data for any
         critical slice this run) is explicitly NOT a failure: backend has
         no way to independently verify slice Recall (that needs the ML
         stack ai-training carries and this service does not), so it can
         only check a report that already exists, never fabricate one.
         Cross-service note: ai-training and backend are separate `uv`
         projects/environments with no shared Python import path, so this
         is NOT a Python function call into `ai_training.evaluation.*` —
         it reads a plain JSON column the other service already writes into
         the SAME Postgres `models` table (identical mechanism the existing
         `recall`/`f1`/`precision`/`latency_ms_p95` gates already rely on),
         rather than adding a new HTTP round-trip between the two services.

    On success: sets `stage=PRODUCTION`, `promoted_by`, `promoted_at`; if a
    different model was PRODUCTION, it is demoted to RETIRED (invariant: at
    most one PRODUCTION model at a time). Both writes happen before the
    audit log entry, mirroring app/services/access_policy_service.py's
    write-then-audit ordering.

    TR-08 (FR-TRN-06): after the promotion itself commits, this dispatches
    the async gallery re-embedding job (`gallery_queue.enqueue_gallery_reembed`)
    so the gallery gets embeddings under the new production version without
    blocking this HTTP response on a full re-embed pass. The dispatch is
    best-effort (a broker outage never undoes the already-successful
    promotion) and fires AFTER the audit log write below, not before —
    the promotion itself is the fact that must be durable first.
    """
    if not confirm:
        raise ConfirmationRequiredError(
            "Promotion requires explicit confirmation: set confirm=true in the request body."
        )

    candidate = model_repo.get(version)
    if candidate is None:
        raise ModelVersionNotFoundError(version)

    current_production = model_repo.get_current_production()
    # A CANDIDATE can never already be the current PRODUCTION model (gate
    # below rejects non-CANDIDATE stages), so `current_production is None`
    # is the only way this is genuinely the first-ever promotion.
    is_first_promotion = current_production is None

    reasons: list[str] = []

    if candidate.stage != ModelStage.CANDIDATE:
        reasons.append(
            f"Model '{version}' is stage {candidate.stage.value}, not CANDIDATE — only a "
            "CANDIDATE model can be promoted."
        )

    if not is_first_promotion:
        candidate_recall = candidate.recall if candidate.recall is not None else -1.0
        production_recall = (
            current_production.recall if current_production.recall is not None else 0.0
        )
        if candidate_recall < production_recall:
            reasons.append(
                f"Candidate recall {candidate_recall:.4f} is below current production "
                f"({current_production.version}) recall {production_recall:.4f} — "
                "promotion would regress recall (FR-TRN-05 no-regression gate)."
            )

    budget = settings.promotion_latency_budget_ms
    latency = candidate.latency_ms_p95
    if latency is None or latency > budget:
        reasons.append(
            f"Candidate p95 latency {latency if latency is not None else 'unknown'}ms exceeds "
            f"the {budget}ms budget (NFR-PRF-01)."
        )

    slice_gate_report = candidate.slice_gate_report
    if slice_gate_report is not None and slice_gate_report.get("passes") is False:
        failed_slices = slice_gate_report.get("failed_slices") or []
        per_slice = slice_gate_report.get("per_slice") or {}
        for slice_name in failed_slices:
            detail = per_slice.get(slice_name, {})
            slice_reason = detail.get("reason") or (
                f"slice '{slice_name}' regressed beyond tolerance"
            )
            reasons.append(f"EC-QA-01 slice regression gate failed: {slice_reason}")
        if not failed_slices:
            # Defensive fallback: passes=False with no failed_slices listed
            # would be an internal inconsistency in the report itself — do
            # not silently ignore it, but also do not pretend to know which
            # slice caused it.
            reasons.append(
                "EC-QA-01 slice regression gate reported passes=False without "
                "identifying which slice(s) failed."
            )

    if reasons:
        raise PromotionGateError(reasons)

    now = datetime.now(UTC)

    if current_production is not None:
        current_production.stage = ModelStage.RETIRED
        model_repo.update(current_production)

    candidate.stage = ModelStage.PRODUCTION
    candidate.promoted_by = actor
    candidate.promoted_at = now
    candidate = model_repo.update(candidate)

    audit_repo.record(
        actor=str(actor),
        action="model.promoted",
        entity=f"model:{version}",
        payload={
            "promoted_version": version,
            "retired_version": (
                current_production.version if current_production is not None else None
            ),
            "recall": candidate.recall,
            "f1": candidate.f1,
            "precision": candidate.precision,
            "latency_ms_p95": candidate.latency_ms_p95,
            "first_promotion": is_first_promotion,
            "slice_gate_report_present": slice_gate_report is not None,
        },
    )

    # FR-TRN-06 (TR-08): dispatch gallery re-embedding for the newly
    # PRODUCTION version. Fires after the promotion + audit write above are
    # already durable — best-effort, never undoes the promotion itself.
    gallery_queue.enqueue_gallery_reembed(candidate.version)

    return candidate
