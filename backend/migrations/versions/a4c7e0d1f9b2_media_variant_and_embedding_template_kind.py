"""media variant + embedding masked/template_kind columns (EC-BE-02,
TSD-edge-cases.md D-4.1/D-10)

Gelombang 1 quick-win migration: prerequisite for the A-4 masked-template
pipeline and its D-4.5 backfill job. Entirely additive.

`media_objects`:
  - `variant` (nullable, new native enum `media_variant`:
    `default|no_glasses|glasses|pitch_ext`) — capture variant recorded at
    presign time. Left NULLABLE (rather than NOT NULL DEFAULT 'default')
    because it describes ROWS THAT ALREADY EXIST before this migration ran,
    and there is no way to know retroactively which of those were
    conceptually "default" captures vs. something else — NULL here means
    "no variant on record" (pre-EC-BE-02 row), which is a more honest
    backfill than silently asserting `default` for history we don't
    actually know. Going forward, `app/services/media_service.py::
    request_presign` always writes an explicit `MediaVariant.DEFAULT` (or
    whatever `PresignRequest.variant` says) for every NEW row, so in
    practice only legacy rows are ever NULL. `POST .../media/presign`
    without a `variant` field in the body continues to work unchanged
    (Pydantic default `None` -> service layer defaults to `default`).

`face_embeddings`:
  - `masked` (NOT NULL, `boolean`, DEFAULT `false`) — every embedding that
    exists today came from an unmasked capture, so `false` is a safe,
    unambiguous backfill (unlike `variant` above, there's no uncertainty
    here: nothing before this migration ever set a masked flag, so
    "unmasked" is simply correct for every existing row).
  - `template_kind` (NOT NULL, new native enum `template_kind`:
    `enrolled|synthetic_masked|recent`, DEFAULT `enrolled`) — same
    reasoning: every row written before the A-4/D-4.5 (`synthetic_masked`)
    and D-6 (`recent`) pipelines exist can only have come from the ordinary
    enrollment embedding pipeline (TR-03), so backfilling to `enrolled` via
    `server_default` on the same `ADD COLUMN` is exact, not a guess. This
    also covers `ai-training`'s `embedding_repo.upsert_embeddings`, which
    does not set this column explicitly today, without changing that code.

Revision ID: a4c7e0d1f9b2
Revises: e5a9f2c1b3d6
Create Date: 2026-09-01 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a4c7e0d1f9b2"
down_revision: str | None = "e5a9f2c1b3d6"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

MEDIA_VARIANT = postgresql.ENUM(
    "default", "no_glasses", "glasses", "pitch_ext", name="media_variant", create_type=False
)
TEMPLATE_KIND = postgresql.ENUM(
    "enrolled", "synthetic_masked", "recent", name="template_kind", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    MEDIA_VARIANT.create(bind, checkfirst=True)
    TEMPLATE_KIND.create(bind, checkfirst=True)

    op.add_column(
        "media_objects",
        sa.Column("variant", MEDIA_VARIANT, nullable=True),
    )

    op.add_column(
        "face_embeddings",
        sa.Column(
            "masked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "face_embeddings",
        sa.Column(
            "template_kind",
            TEMPLATE_KIND,
            nullable=False,
            server_default="enrolled",
        ),
    )


def downgrade() -> None:
    op.drop_column("face_embeddings", "template_kind")
    op.drop_column("face_embeddings", "masked")

    op.drop_column("media_objects", "variant")

    bind = op.get_bind()
    TEMPLATE_KIND.drop(bind, checkfirst=True)
    MEDIA_VARIANT.drop(bind, checkfirst=True)
