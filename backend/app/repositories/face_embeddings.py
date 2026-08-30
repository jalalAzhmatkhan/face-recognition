"""Repository for `face_embeddings` (BE-08).

No prior task wrote embeddings yet (TR-03 will, once the real embedding
pipeline lands), so this is the first repository for the table — kept
minimal on purpose: only what BE-08's revocation cleanup job needs
(`list_for_session` for the deleted-count audit payload, `delete_for_session`
for the actual hard delete). Mirrors the plain get/list/create pattern from
`app/repositories/media_objects.py` — no business logic here.

TSD §6 restricts embedding *read* access at the DB-role level; this
repository itself does not relax that — it is only ever invoked from
trusted backend/worker code, never exposes vectors via an API response.
"""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.face_embedding import FaceEmbedding


class FaceEmbeddingRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_for_session(self, session_id: uuid.UUID) -> list[FaceEmbedding]:
        stmt = select(FaceEmbedding).where(FaceEmbedding.session_id == session_id)
        return list(self._session.scalars(stmt))

    def delete_for_session(self, session_id: uuid.UUID) -> int:
        """Hard-delete every embedding row for `session_id`.

        Returns the number of rows deleted (used for the
        `enrollment.revoke_completed` audit payload). Safe to call more than
        once — a second call simply deletes 0 rows (SQL `DELETE ... WHERE`
        with no matches is not an error), which is exactly what makes the
        revocation cleanup job idempotent (BE-08, NFR-OPS-02).
        """
        stmt = delete(FaceEmbedding).where(FaceEmbedding.session_id == session_id)
        result = self._session.execute(stmt)
        self._session.commit()
        return result.rowcount or 0
