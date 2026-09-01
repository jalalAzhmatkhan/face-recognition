"""Request/response contracts for `{API_V1_PREFIX}/training/jobs/*` and
`{API_V1_PREFIX}/models/*` (BE-13, TSD §7, FR-TRN-02/05; job_type/params/
snapshot_id added by EC-BE-03, TSD-edge-cases.md B-1/D-10)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import ModelStage, TrainingJobStatus, TrainingJobType


class TrainingJobCreateRequest(BaseModel):
    """`job_type` defaults to `EVALUATION` for exact backward compatibility:
    every request body that worked before EC-BE-03 (no `job_type` field at
    all) still validates identically today — same required fields
    (`model_version` + `benchmark_id`), same defaults, zero behaviour
    change for existing clients.

    Per-type required-field validation (`_validate_required_fields_per_type`
    below) is a DRAFT for the four new types — TSD-edge-cases.md B-1..B-3
    only pins down exact `params` shape for `FINETUNE_EMBEDDER`
    (`params.augmentations`) and `FINETUNE_LIVENESS` (`params.dataset_ref`);
    `GALLERY_REEMBED` and `BACKFILL_MASKED_TEMPLATES` have no documented
    required params yet, so validation for them is intentionally minimal
    (just what's already implied by how the existing/planned Celery tasks
    consume these jobs — see field-level comments) and may be tightened by
    the tasks that actually implement those jobs (B-2/B-3/D-4.5).
    """

    job_type: TrainingJobType = TrainingJobType.EVALUATION
    model_version: str | None = Field(None, min_length=1, max_length=64)
    benchmark_id: str | None = Field(None, min_length=1, max_length=255)
    snapshot_id: str | None = Field(None, min_length=1, max_length=64)
    params: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_required_fields_per_type(self) -> "TrainingJobCreateRequest":
        errors: list[str] = []

        if self.job_type == TrainingJobType.EVALUATION:
            # UNCHANGED from pre-EC-BE-03 behaviour: both fields required.
            if not self.model_version:
                errors.append("model_version is required for job_type=EVALUATION")
            if not self.benchmark_id:
                errors.append("benchmark_id is required for job_type=EVALUATION")

        elif self.job_type == TrainingJobType.FINETUNE_EMBEDDER:
            # B-2: params.augmentations = list of toggles (mask_mlfw,
            # occlusion_ocfr, multi_resolution, alignment_perturb_aroface,
            # brightness_gamma). At least one augmentation must be selected
            # — an empty/absent list would mean "fine-tune with nothing
            # enabled", which is not a meaningful job.
            augmentations = (self.params or {}).get("augmentations")
            if not isinstance(augmentations, list) or not augmentations:
                errors.append(
                    "params.augmentations (non-empty list) is required for "
                    "job_type=FINETUNE_EMBEDDER"
                )

        elif self.job_type == TrainingJobType.FINETUNE_LIVENESS:
            # B-3: params.dataset_ref points at the local PAD dataset.
            dataset_ref = (self.params or {}).get("dataset_ref")
            if not isinstance(dataset_ref, str) or not dataset_ref.strip():
                errors.append(
                    "params.dataset_ref (non-empty string) is required for "
                    "job_type=FINETUNE_LIVENESS"
                )

        elif self.job_type == TrainingJobType.GALLERY_REEMBED:
            # Mirrors the existing post-promote dispatch
            # (gallery_queue.enqueue_gallery_reembed(model_version)) — a
            # re-embed job re-extracts the gallery with a specific model
            # version, so that version must be named explicitly.
            if not self.model_version:
                errors.append(
                    "model_version is required for job_type=GALLERY_REEMBED"
                )

        # BACKFILL_MASKED_TEMPLATES (D-4.5): a one-off job that iterates all
        # ENROLLED sessions — no required fields beyond job_type itself.
        # `snapshot_id`/`params` stay fully optional for this type.

        if errors:
            raise ValueError("; ".join(errors))
        return self


class TrainingJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_type: TrainingJobType
    model_version: str | None
    benchmark_id: str | None
    snapshot_id: str | None
    params: dict[str, Any] | None
    status: TrainingJobStatus
    triggered_by: uuid.UUID
    created_at: datetime
    completed_at: datetime | None
    error_message: str | None
    mlflow_run_id: str | None


class TrainingJobListResponse(BaseModel):
    items: list[TrainingJobResponse]
    total: int
    limit: int
    offset: int


class ModelVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: str
    mlflow_run_id: str
    stage: ModelStage
    recall: float | None
    f1: float | None
    precision: float | None
    latency_ms_p95: int | None
    promoted_by: uuid.UUID | None
    promoted_at: datetime | None


class ModelVersionListResponse(BaseModel):
    items: list[ModelVersionResponse]


class ModelPromoteRequest(BaseModel):
    """`confirm` MUST be `true` (FR-TRN-05: promotion is human-in-the-loop,
    never triggered by an empty/default-bodied or automated request)."""

    confirm: bool = False


class ModelPromoteResponse(BaseModel):
    version: str
    stage: ModelStage
    promoted_by: uuid.UUID
    promoted_at: datetime
