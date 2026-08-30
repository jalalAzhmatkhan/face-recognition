"""face_embeddings — pgvector gallery (TSD §4, cosine HNSW index added in migration).

Embedding read access is restricted at the DB-role level (TSD §6: "restrict embedding
read access; never expose vectors via API") — see backend/README.md for the
`embeddings_write` role granted to ai-training.
"""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
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
