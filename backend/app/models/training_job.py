"""training_jobs — manual/automatic training-evaluation job runs (BE-13,
FR-TRN-02/03; job_type/params/snapshot_id added by EC-BE-03,
TSD-edge-cases.md B-1/D-10).

`model_version` is deliberately a plain string column, NOT a real
`ForeignKey("models.version")` — a training job is created (POST
/api/v1/training/jobs) BEFORE any `models` row for that version necessarily
exists; the `models` row is only created/upserted by the ai-training worker
once `evaluate_candidate` finishes (see
ai_training/worker/tasks.py::run_training_evaluation_job). A hard FK
constraint would make job creation fail for exactly the common case this
table exists to support. This is what the task brief calls a "loose" FK,
and `snapshot_id` below follows the identical convention.

`benchmark_id` was NOT NULL before EC-BE-03 (every job was an EVALUATION,
which always has one). It is now nullable at the DB level because
non-EVALUATION job types (FINETUNE_EMBEDDER/FINETUNE_LIVENESS/
GALLERY_REEMBED/BACKFILL_MASKED_TEMPLATES) do not necessarily have a
benchmark — the per-type "is it actually required" rule lives in
`TrainingJobCreateRequest`'s validator (app/schemas/training.py), not the
DB column. EVALUATION's Pydantic validation still requires it, so existing
EVALUATION rows/behaviour are unaffected.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import TrainingJobStatus, TrainingJobType
from app.models.mixins import CreatedAtMixin, UUIDPKMixin


class TrainingJob(UUIDPKMixin, CreatedAtMixin, Base):
    __tablename__ = "training_jobs"

    job_type: Mapped[TrainingJobType] = mapped_column(
        Enum(TrainingJobType, name="training_job_type", native_enum=True),
        nullable=False,
        default=TrainingJobType.EVALUATION,
        server_default=TrainingJobType.EVALUATION.value,
    )
    # No ForeignKey — see module docstring.
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    benchmark_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # No ForeignKey — `snapshot_id` is an S3 manifest id (UUID string) minted
    # by ai_training.data.snapshots.build_snapshot, not a DB row anywhere
    # (see that module's docstring: "A snapshot is a versioned JSON manifest
    # in S3", no snapshots table exists).
    snapshot_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    params: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[TrainingJobStatus] = mapped_column(
        Enum(TrainingJobStatus, name="training_job_status", native_enum=True),
        nullable=False,
        default=TrainingJobStatus.PENDING,
        server_default=TrainingJobStatus.PENDING.value,
    )
    triggered_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("staff_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    mlflow_run_id: Mapped[str | None] = mapped_column(String(255))

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"TrainingJob(id={self.id!r}, job_type={self.job_type!r}, "
            f"model_version={self.model_version!r}, status={self.status!r})"
        )
