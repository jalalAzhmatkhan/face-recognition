"""training_jobs — manual/automatic training-evaluation job runs (BE-13,
FR-TRN-02/03).

`model_version` is deliberately a plain string column, NOT a real
`ForeignKey("models.version")` — a training job is created (POST
/api/v1/training/jobs) BEFORE any `models` row for that version necessarily
exists; the `models` row is only created/upserted by the ai-training worker
once `evaluate_candidate` finishes (see
ai_training/worker/tasks.py::run_training_evaluation_job). A hard FK
constraint would make job creation fail for exactly the common case this
table exists to support. This is what the task brief calls a "loose" FK:
logically-related, not DB-enforced.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import TrainingJobStatus
from app.models.mixins import CreatedAtMixin, UUIDPKMixin


class TrainingJob(UUIDPKMixin, CreatedAtMixin, Base):
    __tablename__ = "training_jobs"

    # No ForeignKey — see module docstring.
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    benchmark_id: Mapped[str] = mapped_column(String(255), nullable=False)
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
            f"TrainingJob(id={self.id!r}, model_version={self.model_version!r}, "
            f"status={self.status!r})"
        )
