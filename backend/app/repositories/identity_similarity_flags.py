"""Repository for `identity_similarity_flags` (EC-BE-04, TSD-edge-cases.md
D-4.4). See app/models/identity_similarity_flag.py for the table's purpose
and consumers.
"""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.identity_similarity_flag import IdentitySimilarityFlag


class IdentitySimilarityFlagRepository:
    """Thin data-access wrapper around a SQLAlchemy `Session`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, flag_id: uuid.UUID) -> IdentitySimilarityFlag | None:
        return self._session.get(IdentitySimilarityFlag, flag_id)

    def list(
        self, *, limit: int = 100, offset: int = 0
    ) -> list[IdentitySimilarityFlag]:
        stmt = (
            select(IdentitySimilarityFlag)
            .order_by(IdentitySimilarityFlag.flagged_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self._session.scalars(stmt))

    def list_for_user(self, user_id: uuid.UUID) -> list[IdentitySimilarityFlag]:
        """Flags involving `user_id` on either side of the (unordered) pair."""
        stmt = select(IdentitySimilarityFlag).where(
            or_(
                IdentitySimilarityFlag.user_a_id == user_id,
                IdentitySimilarityFlag.user_b_id == user_id,
            )
        )
        return list(self._session.scalars(stmt))

    def create(self, flag: IdentitySimilarityFlag) -> IdentitySimilarityFlag:
        self._session.add(flag)
        self._session.commit()
        self._session.refresh(flag)
        return flag
