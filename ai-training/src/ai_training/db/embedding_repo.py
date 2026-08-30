"""Raw-SQL `face_embeddings` upsert (TR-03, FR-ENR-07).

`face_embeddings.id` is a client-side-generated UUID (see
`backend/app/models/mixins.py::UUIDPKMixin` — `default=uuid.uuid4`, no DB
`gen_random_uuid()` server default), so this module generates ids in Python
rather than relying on a Postgres extension/default that isn't there.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from ai_training.db.enrollment_repo import Cursor

if TYPE_CHECKING:
    from ai_training.embedding.extractor import PoseBucketEmbedding


def upsert_embeddings(
    cursor: Cursor,
    *,
    user_id: str,
    session_id: str,
    model_version: str,
    embeddings: list[PoseBucketEmbedding],
) -> int:
    """Replace this session's gallery templates for `model_version`.

    There is no unique constraint on `(session_id, pose_bucket,
    model_version)` in the schema (see `backend/app/models/face_embedding.py`),
    so "upsert" here means delete-then-insert within the same transaction —
    simpler than an `ON CONFLICT` clause with no conflict target, and safe
    to re-run (a retried/duplicate embedding job for the same session
    produces the same end state, not duplicate rows).
    """
    cursor.execute(
        "DELETE FROM face_embeddings WHERE session_id = %s AND model_version = %s",
        (session_id, model_version),
    )
    inserted = 0
    for embedding in embeddings:
        cursor.execute(
            "INSERT INTO face_embeddings "
            "(id, user_id, session_id, model_version, pose_bucket, vector) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                str(uuid.uuid4()),
                user_id,
                session_id,
                model_version,
                embedding.pose_bucket,
                embedding.vector,
            ),
        )
        inserted += 1
    return inserted
