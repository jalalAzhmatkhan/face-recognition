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

from app.core.config import Settings
from app.models.enums import ModelStage, TrainingJobStatus
from app.models.model_registry import ModelVersion
from app.models.training_job import TrainingJob
from app.repositories.audit_logs import AuditLogRepository
from app.repositories.model_versions import ModelVersionRepository
from app.repositories.training_jobs import TrainingJobRepository
from app.services import training_queue


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
    model_version: str,
    benchmark_id: str,
    actor: uuid.UUID,
) -> TrainingJob:
    job = TrainingJob(
        model_version=model_version,
        benchmark_id=benchmark_id,
        status=TrainingJobStatus.PENDING,
        triggered_by=actor,
    )
    job = job_repo.create(job)

    audit_repo.record(
        actor=str(actor),
        action="training.job_created",
        entity=f"training_job:{job.id}",
        payload={"model_version": model_version, "benchmark_id": benchmark_id},
    )

    training_queue.enqueue_training_job(job.id, model_version, benchmark_id)
    return job


def get_training_job(job_repo: TrainingJobRepository, job_id: uuid.UUID) -> TrainingJob:
    job = job_repo.get(job_id)
    if job is None:
        raise TrainingJobNotFoundError(str(job_id))
    return job


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

    On success: sets `stage=PRODUCTION`, `promoted_by`, `promoted_at`; if a
    different model was PRODUCTION, it is demoted to RETIRED (invariant: at
    most one PRODUCTION model at a time). Both writes happen before the
    audit log entry, mirroring app/services/access_policy_service.py's
    write-then-audit ordering.
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

    # FR-TRN-06 (re-extract gallery embeddings with the new model version) is
    # explicitly NOT triggered here — that is TR-08, a separate follow-up
    # task. Nothing in this function queues, stubs, or pretends to start it.
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
        },
    )
    return candidate
