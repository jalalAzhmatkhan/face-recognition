"""system_parameters — ADMIN-tunable operational knobs ("System Parameter" menu)

Brand-new, additive table. First consumer: `enrollment_capture_quality`
(min sharpness / brightness range for the Enrollment capture wizard's live
preflight AND ai-training's server-side QC gate) — see
`app/models/system_parameter.py` and `app/services/system_parameter_
service.py` for the resolution contract (a missing row = built-in default,
same "override, not source of truth" shape as `recognition_configs`,
migration `c7d4b1a9e3f6`).

`ai_training_embeddings_write` is granted SELECT explicitly: per migration
`a1c8f4d0e7b3`'s docstring, that is the ONE role ai-training's worker
actually connects as today (a documented "KNOWN GAP" in
`ai_training/config.py`'s `DBSettings`) — `ai_training_ro`'s `ALTER DEFAULT
PRIVILEGES` grant (migration `3a5b0a58f7ab`) does NOT cover it, so a
brand-new table is invisible to the worker's real runtime role unless
granted here, same reasoning as that migration's own grants.

No `ai_inference_ro` grant: nothing in the `/recognize` decision path reads
`enrollment_capture_quality` (it's an enrollment-capture-only knob).

Revision ID: d1e5c8a3f7b2
Revises: c8f3a2e6d9b1
Create Date: 2026-09-01 17:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d1e5c8a3f7b2"
down_revision: str | None = "c8f3a2e6d9b1"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

EMBEDDINGS_WRITE_ROLE = "ai_training_embeddings_write"


def upgrade() -> None:
    op.create_table(
        "system_parameters",
        sa.Column("key", sa.String(length=128), primary_key=True),
        sa.Column("value", postgresql.JSONB, nullable=False),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("staff_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.execute(f"GRANT SELECT ON system_parameters TO {EMBEDDINGS_WRITE_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE SELECT ON system_parameters FROM {EMBEDDINGS_WRITE_ROLE}")
    op.drop_table("system_parameters")
