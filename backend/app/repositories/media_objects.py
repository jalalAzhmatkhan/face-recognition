"""Repository for `media_objects` (BE-06, BE-14).

Mirrors the minimal get/list/create/update pattern established by
`app/repositories/enrollments.py` — no business logic (presign validation,
S3 HEAD verification, retention-window math) here, just data access.
"""

import uuid
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import MediaKind, MediaObjectStatus
from app.models.media_object import MediaObject


class MediaObjectRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, media_id: uuid.UUID) -> MediaObject | None:
        return self._session.get(MediaObject, media_id)

    def list_for_session(
        self,
        session_id: uuid.UUID,
        *,
        kind: MediaKind | None = None,
        status: MediaObjectStatus | None = None,
    ) -> list[MediaObject]:
        stmt = (
            select(MediaObject)
            .where(MediaObject.session_id == session_id)
            .order_by(MediaObject.created_at)
        )
        if kind is not None:
            stmt = stmt.where(MediaObject.kind == kind)
        if status is not None:
            stmt = stmt.where(MediaObject.status == status)
        return list(self._session.scalars(stmt))

    def create(self, media: MediaObject) -> MediaObject:
        self._session.add(media)
        self._session.commit()
        self._session.refresh(media)
        return media

    def update(self, media: MediaObject) -> MediaObject:
        self._session.add(media)
        self._session.commit()
        self._session.refresh(media)
        return media

    def delete(self, media: MediaObject) -> None:
        self._session.delete(media)
        self._session.commit()

    def list_finalized_without_retention(
        self, *, kinds: Iterable[MediaKind]
    ) -> list[MediaObject]:
        """FINALIZED rows of the given kind(s) that don't have
        `retention_expires_at` set yet (BE-14 backfill target set)."""
        stmt = (
            select(MediaObject)
            .where(MediaObject.status == MediaObjectStatus.FINALIZED)
            .where(MediaObject.retention_expires_at.is_(None))
            .where(MediaObject.kind.in_(list(kinds)))
        )
        return list(self._session.scalars(stmt))

    def list_expired(self, *, now: datetime) -> list[MediaObject]:
        """Rows whose retention window has passed (BE-14 purge target set)."""
        stmt = select(MediaObject).where(
            MediaObject.retention_expires_at.is_not(None),
            MediaObject.retention_expires_at <= now,
        )
        return list(self._session.scalars(stmt))
