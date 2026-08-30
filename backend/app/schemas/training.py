"""Request/response contracts for `{API_V1_PREFIX}/training/jobs/*` and
`{API_V1_PREFIX}/models/*` (BE-13, TSD §7, FR-TRN-02/05)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ModelStage, TrainingJobStatus


class TrainingJobCreateRequest(BaseModel):
    model_version: str = Field(..., min_length=1, max_length=64)
    benchmark_id: str = Field(..., min_length=1, max_length=255)


class TrainingJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    model_version: str | None
    benchmark_id: str
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
