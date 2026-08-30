"""media object status (BE-06)

Additive migration: adds a `status` column to `media_objects` so a row can
represent "a presigned upload URL was issued, upload not yet verified"
(`PENDING`) separately from "S3 HEAD confirmed the object exists and its
metadata was verified" (`FINALIZED`) — see app/models/enums.py
`MediaObjectStatus` and app/services/media_service.py.

Existing columns (`checksum`, `size`, `content_type`) are untouched: for a
PENDING row they hold the client's claim recorded at presign time; for a
FINALIZED row they hold what `POST /enrollments/{id}/complete` read back
from S3 HEAD. No existing migration is altered or replaced.

Revision ID: bcf250963057
Revises: 48b08e41d49a
Create Date: 2026-08-30 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "bcf250963057"
down_revision: str | None = "48b08e41d49a"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

MEDIA_OBJECT_STATUS = ("PENDING", "FINALIZED")


def upgrade() -> None:
    media_object_status = postgresql.ENUM(
        *MEDIA_OBJECT_STATUS, name="media_object_status", create_type=False
    )
    bind = op.get_bind()
    media_object_status.create(bind, checkfirst=True)

    op.add_column(
        "media_objects",
        sa.Column(
            "status",
            media_object_status,
            nullable=False,
            server_default="PENDING",
        ),
    )


def downgrade() -> None:
    op.drop_column("media_objects", "status")

    bind = op.get_bind()
    postgresql.ENUM(name="media_object_status").drop(bind, checkfirst=True)
