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
    from ai_training.embedding.synthetic_masked import SyntheticMaskedTemplate


def has_embeddings_for_model(cursor: Cursor, *, session_id: str, model_version: str) -> bool:
    """TR-08 idempotency check: has this session already been re-embedded
    under `model_version`? Lets `run_gallery_reembed_job` skip work already
    done on a re-run (retried/resumed job, or the same model promoted a
    second time) instead of paying for a redundant download+detect+align+
    embed pass for every already-processed session."""
    cursor.execute(
        "SELECT 1 FROM face_embeddings WHERE session_id = %s AND model_version = %s LIMIT 1",
        (session_id, model_version),
    )
    return cursor.fetchone() is not None


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


def upsert_synthetic_masked_embeddings(
    cursor: Cursor,
    *,
    user_id: str,
    session_id: str,
    model_version: str,
    templates: list[SyntheticMaskedTemplate],
) -> int:
    """A-4 (TSD-edge-cases.md A-4/D-4.5): replace this session's
    `synthetic_masked` templates for `model_version`.

    Scoped delete (`... AND masked = true AND template_kind =
    'synthetic_masked'`) so this NEVER touches the ordinary `enrolled`
    rows `upsert_embeddings` writes for the same `(session_id,
    model_version)` — the two kinds coexist by design (TSD A-4: masked
    probes prefer matching masked templates; ordinary probes still need
    the ordinary `enrolled` templates). Same "delete-then-insert within
    one transaction" idempotency rationale as `upsert_embeddings` — safe
    to re-run for a retried/duplicate job on the same session.
    """
    cursor.execute(
        "DELETE FROM face_embeddings WHERE session_id = %s AND model_version = %s "
        "AND masked = true AND template_kind = 'synthetic_masked'",
        (session_id, model_version),
    )
    inserted = 0
    for template in templates:
        cursor.execute(
            "INSERT INTO face_embeddings "
            "(id, user_id, session_id, model_version, pose_bucket, vector, masked, template_kind) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                str(uuid.uuid4()),
                user_id,
                session_id,
                model_version,
                template.pose_bucket,
                template.vector,
                True,
                "synthetic_masked",
            ),
        )
        inserted += 1
    return inserted
