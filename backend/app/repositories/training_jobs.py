"""Repository for `training_jobs` (BE-13).

Minimal CRUD wrapper, mirrors `app/repositories/access_policies.py`'s
convention. Backend only ever creates a job and reads it back — the
status/error/mlflow_run_id UPDATEs are performed by the ai-training worker
directly via raw SQL (see ai_training/db/training_job_repo.py), not through
this class.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import TrainingJobStatus
from app.models.training_job import TrainingJob


class TrainingJobRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, job_id: uuid.UUID) -> TrainingJob | None:
        return self._session.get(TrainingJob, job_id)

    def create(self, job: TrainingJob) -> TrainingJob:
        self._session.add(job)
        self._session.commit()
        self._session.refresh(job)
        return job

    def list(
        self,
        *,
        status: TrainingJobStatus | None = None,
        model_version: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[TrainingJob]:
        """Newest-first (BE-15) — mirrors `DeviceRepository.list`'s
        limit/offset pagination shape."""
        stmt = (
            select(TrainingJob)
            .order_by(TrainingJob.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if status is not None:
            stmt = stmt.where(TrainingJob.status == status)
        if model_version is not None:
            stmt = stmt.where(TrainingJob.model_version == model_version)
        return list(self._session.scalars(stmt))

    def count(
        self, *, status: TrainingJobStatus | None = None, model_version: str | None = None
    ) -> int:
        stmt = select(func.count()).select_from(TrainingJob)
        if status is not None:
            stmt = stmt.where(TrainingJob.status == status)
        if model_version is not None:
            stmt = stmt.where(TrainingJob.model_version == model_version)
        return self._session.scalar(stmt) or 0
