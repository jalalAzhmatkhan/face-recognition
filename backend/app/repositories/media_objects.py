"""Repository for `media_objects` (BE-06).

Mirrors the minimal get/list/create/update pattern established by
`app/repositories/enrollments.py` — no business logic (presign validation,
S3 HEAD verification) here, just data access.
"""

import uuid

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
