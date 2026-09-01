"""face_embeddings — pgvector gallery (TSD §4, cosine HNSW index added in migration).

Embedding read access is restricted at the DB-role level (TSD §6: "restrict embedding
read access; never expose vectors via API") — see backend/README.md for the
`embeddings_write` role granted to ai-training.
"""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import TemplateKind
from app.models.mixins import UUIDPKMixin

EMBEDDING_DIM = 512


class FaceEmbedding(UUIDPKMixin, Base):
    __tablename__ = "face_embeddings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("enrollment_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    model_version: Mapped[str] = mapped_column(
        String(64), ForeignKey("models.version", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Yaw sector (clock position, e.g. "12", "01", ... "11") the embedding was sampled from.
    pose_bucket: Mapped[str] = mapped_column(String(16), nullable=False)
    vector: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # EC-BE-02 (TSD-edge-cases.md D-4.1/D-10): masked-probe matching support.
    # `masked` flags a template generated FROM a masked face (synthetic
    # MaskTheFace augmentation today, A-4; a genuinely-masked live capture
    # later) so gallery queries can filter to masked-vs-masked matching
    # first (D-4 fallback logic lives in ai-inference, not here). NOT NULL
    # DEFAULT false: every existing/ordinary embedding is an unmasked
    # template, so `false` is a safe, non-error backfill for pre-EC-BE-02
    # rows -- not "opt-in metadata that might be missing".
    masked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Provenance of this template. NOT NULL DEFAULT 'enrolled': every row
    # that existed before this migration (and every row ai-training's
    # `embedding_repo.upsert_embeddings` writes today, since it does not
    # set this column explicitly) came from the ordinary enrollment
    # pipeline, so `server_default` both backfills existing rows AND covers
    # future plain inserts in one step -- see the EC-BE-02 migration.
    # `synthetic_masked` (A-4/D-4.5) and `recent` (D-6) are written
    # explicitly by later tasks' pipelines.
    template_kind: Mapped[TemplateKind] = mapped_column(
        Enum(
            TemplateKind,
            name="template_kind",
            native_enum=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=TemplateKind.ENROLLED,
        server_default=TemplateKind.ENROLLED.value,
    )
