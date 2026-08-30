"""media_objects — S3 media METADATA ONLY, no bytes ever touch this service (TSD §4/§6)."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import MediaKind, MediaObjectStatus
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
        Enum(
            MediaKind,
            name="media_kind",
            native_enum=True,
            # MediaKind is the only enum in this codebase whose DB values
            # (lowercase, per TSD's literal `kind[photo|video|event_frame]`)
            # differ from its Python member names (PHOTO/VIDEO/EVENT_FRAME).
            # Without values_callable, SQLAlchemy binds/reads the member
            # *name* against the native enum type, which the Postgres
            # `media_kind` type rejects (e.g. "VIDEO" vs the allowed
            # "video") -- found live via a real presign/list_for_session
            # call against Postgres, not caught by mocked tests.
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
    )
    s3_bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    s3_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    # Until `status` is FINALIZED, `checksum`/`size`/`content_type` are the
    # CLIENT'S CLAIM recorded at presign time (BE-06) — not yet verified
    # against reality. `POST /enrollments/{id}/complete` overwrites all
    # three with values read back from an S3 HEAD request before flipping
    # `status` to FINALIZED (see app/services/media_service.py). Never
    # trust these columns for a PENDING row.
    checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[MediaObjectStatus] = mapped_column(
        Enum(MediaObjectStatus, name="media_object_status", native_enum=True),
        nullable=False,
        default=MediaObjectStatus.PENDING,
        server_default=MediaObjectStatus.PENDING.value,
    )
    # ASM-10: 90-day raw-media expiry, enforced by a retention job (BE-14).
    retention_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
