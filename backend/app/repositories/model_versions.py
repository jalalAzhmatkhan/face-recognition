"""Repository for `models` (`ModelVersion`, TSD §4/§7, FR-TRN-05).

The table (and ORM model) has existed since BE-02
(`app/models/model_registry.py`) but had no router/repository/schema until
BE-13. Backend only ever READS this table (list/get/promote-gate checks) —
writing `recall`/`f1`/`precision`/`latency_ms_p95`/`mlflow_run_id` after an
evaluation run is the ai-training worker's job
(`ai_training.db.training_job_repo`), not this repository's. `update()` here
exists ONLY for the promotion mutation (stage/promoted_by/promoted_at),
which IS a backend-owned write per FR-TRN-05's human-in-the-loop gate.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ModelStage
from app.models.model_registry import ModelVersion


class ModelVersionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, version: str) -> ModelVersion | None:
        return self._session.get(ModelVersion, version)

    def list(self, *, stage: ModelStage | None = None) -> list[ModelVersion]:
        stmt = select(ModelVersion).order_by(ModelVersion.version)
        if stage is not None:
            stmt = stmt.where(ModelVersion.stage == stage)
        return list(self._session.scalars(stmt))

    def get_current_production(self) -> ModelVersion | None:
        stmt = select(ModelVersion).where(ModelVersion.stage == ModelStage.PRODUCTION)
        return self._session.scalars(stmt).first()

    def update(self, model: ModelVersion) -> ModelVersion:
        self._session.add(model)
        self._session.commit()
        self._session.refresh(model)
        return model
