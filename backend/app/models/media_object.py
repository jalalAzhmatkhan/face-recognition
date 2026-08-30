"""media_objects — S3 media METADATA ONLY, no bytes ever touch this service (TSD §4/§6)."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import MediaKind
from app.models.mixins import CreatedAtMixin, UUIDPKMixin


class MediaObject(UUIDPKMixin, CreatedAtMixin, Base):
    __tablename__ = "media_objects"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("enrollment_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[MediaKind] = mapped_column(
        Enum(MediaKind, name="media_kind", native_enum=True), nullable=False
    )
    s3_bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    s3_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    # ASM-10: 90-day raw-media expiry, enforced by a retention job (BE-14).
    retention_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
