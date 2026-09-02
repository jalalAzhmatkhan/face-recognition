"""media_objects.clock_position (video -> per-clock-position photo capture)

Phase 2 of replacing the single 360-degree enrollment VIDEO with a set of
still photos captured automatically at each of the 12 clock positions.

Why a dedicated column rather than reusing what exists: `kind` says
photo/video/event_frame and `variant` says which CAPTURE VARIANT a shot
belongs to (`default|no_glasses|glasses|pitch_ext`, EC-BE-02) -- neither can
express "this photo is the 5 o'clock frame of the sweep". Encoding it in the
S3 key alone was rejected: `ai-training` would then have to parse object
keys to bucket frames, which is exactly the kind of stringly-typed coupling
`media_objects` exists to avoid.

Nullable, and NOT unique per session:
  - `NULL` = a photo with no sweep position -- the frontal preflight shot
    (`photo_1.jpg`, which doubles as the neutral-pose reference, see
    `ai_training.db.enrollment_repo.get_frontal_photo`), every photo
    predating this column, and every video/event_frame row.
  - Several rows legitimately share one position: the wizard captures a
    short BURST per position (a single still would collapse
    `extract_gallery_embeddings`' 3-frame averaging down to one sample,
    losing both sharpness selection and noise averaging), and a re-shot
    position simply appends more candidates for QC to choose between.

Purely additive: no existing row or code path changes meaning, and the
legacy one-video-per-session shape keeps working until the frontend is
switched over (phase 3).

Revision ID: e4b9d2f6a8c3
Revises: d1e5c8a3f7b2
Create Date: 2026-09-02 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e4b9d2f6a8c3"
down_revision: str | None = "d1e5c8a3f7b2"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "media_objects",
        sa.Column("clock_position", sa.SmallInteger(), nullable=True),
    )
    op.create_check_constraint(
        "ck_media_objects_clock_position_range",
        "media_objects",
        "clock_position IS NULL OR (clock_position BETWEEN 1 AND 12)",
    )
    # QC and the embedding extractor both read a session's photos grouped by
    # position; this is the access path for that, and for the frontal-photo
    # lookup (`clock_position IS NULL`).
    op.create_index(
        "ix_media_objects_session_clock_position",
        "media_objects",
        ["session_id", "clock_position"],
    )


def downgrade() -> None:
    op.drop_index("ix_media_objects_session_clock_position", table_name="media_objects")
    op.drop_constraint("ck_media_objects_clock_position_range", "media_objects", type_="check")
    op.drop_column("media_objects", "clock_position")
