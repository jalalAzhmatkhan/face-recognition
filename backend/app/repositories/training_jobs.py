"""Repository for `training_jobs` (BE-13).

Minimal CRUD wrapper, mirrors `app/repositories/access_policies.py`'s
convention. Backend only ever creates a job and reads it back — the
status/error/mlflow_run_id UPDATEs are performed by the ai-training worker
directly via raw SQL (see ai_training/db/training_job_repo.py), not through
this class.
"""

import uuid

from sqlalchemy.orm import Session

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
