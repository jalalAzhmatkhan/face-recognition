"""Repository for `recognition_configs` (EC-BE-04, TSD-edge-cases.md D-4.2).

`from __future__ import annotations` (PEP 563) is used here for the same
reason as `app/repositories/access_policies.py`: this class defines a method
literally named `list`, which would otherwise shadow the `list[...]` builtin
in later return-type annotations at class-body-exec time.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import RecognitionConfigScope
from app.models.recognition_config import RecognitionConfig


class RecognitionConfigRepository:
    """Thin data-access wrapper around a SQLAlchemy `Session`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, config_id: uuid.UUID) -> RecognitionConfig | None:
        return self._session.get(RecognitionConfig, config_id)

    def get_by_key(
        self, *, scope: RecognitionConfigScope, scope_ref: str | None, mode: str
    ) -> RecognitionConfig | None:
        """Look up the single row for an exact `(scope, scope_ref, mode)`
        override key — used both for the pre-insert duplicate check
        (service layer translates a hit into a 409) and by
        `resolve_recognition_config`'s per-candidate-scope lookup."""
        stmt = select(RecognitionConfig).where(
            RecognitionConfig.scope == scope,
            RecognitionConfig.scope_ref == scope_ref,
            RecognitionConfig.mode == mode,
        )
        return self._session.scalars(stmt).first()

    def list(
        self,
        *,
        scope: RecognitionConfigScope | None = None,
        scope_ref: str | None = None,
        mode: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RecognitionConfig]:
        stmt = (
            select(RecognitionConfig)
            .order_by(RecognitionConfig.scope, RecognitionConfig.mode)
            .limit(limit)
            .offset(offset)
        )
        if scope is not None:
            stmt = stmt.where(RecognitionConfig.scope == scope)
        if scope_ref is not None:
            stmt = stmt.where(RecognitionConfig.scope_ref == scope_ref)
        if mode is not None:
            stmt = stmt.where(RecognitionConfig.mode == mode)
        return list(self._session.scalars(stmt))

    def count(
        self,
        *,
        scope: RecognitionConfigScope | None = None,
        scope_ref: str | None = None,
        mode: str | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(RecognitionConfig)
        if scope is not None:
            stmt = stmt.where(RecognitionConfig.scope == scope)
        if scope_ref is not None:
            stmt = stmt.where(RecognitionConfig.scope_ref == scope_ref)
        if mode is not None:
            stmt = stmt.where(RecognitionConfig.mode == mode)
        return self._session.scalar(stmt) or 0

    def create(self, config: RecognitionConfig) -> RecognitionConfig:
        self._session.add(config)
        self._session.commit()
        self._session.refresh(config)
        return config

    def update(self, config: RecognitionConfig) -> RecognitionConfig:
        self._session.add(config)
        self._session.commit()
        self._session.refresh(config)
        return config

    def delete(self, config: RecognitionConfig) -> None:
        self._session.delete(config)
        self._session.commit()
