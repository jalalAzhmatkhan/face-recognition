"""models.model_kind registry split (EC-BE-06, TSD-edge-cases.md B-3)

Additive migration: adds `models.model_kind` (new native enum `model_kind`:
`embedder|liveness`, NOT NULL, backfilled `embedder`). Every row that
exists today came from the pre-edge-case embedder training/evaluation path
(the only kind that ever existed), so `embedder` is an exact backfill, not
a guess (same reasoning as migration `a4c7e0d1f9b2`'s `face_embeddings.
masked`/`template_kind` columns) - unlike `media_objects.variant` in that
same migration, there is no ambiguity here to leave NULL for.

`server_default` stays in place permanently (not just for this migration's
backfill): `app/services/training_service.py::create_training_job`/the
ai-training worker's `EVALUATION` job path still never sets `model_kind`
explicitly, so every row written before EC-TR-07's `FINETUNE_LIVENESS` job
exists keeps defaulting correctly to `embedder` with no code change needed
there.

Application-layer consequences (not part of this migration, cross-referenced
here for anyone reading the schema history):
  - `app/repositories/model_versions.py::get_current_production` now takes
    a required `model_kind` argument - each kind has its own independent
    PRODUCTION slot, so a query with no kind filter would risk returning
    (or retiring) the WRONG kind's production model.
  - `app/services/training_service.py::promote_model` scopes its
    current-production lookup, its no-regression-vs-production gate, and
    its EC-QA-01 slice-gate check to `model_kind == EMBEDDER` only -
    LIVENESS candidates skip both (their real gate, BPCER@APCER per mode,
    lands with EC-TR-07/EC-IN-05/EC-QA-03; until then LIVENESS promotion is
    confirmation + latency-budget only, never silently blocked by a
    Recall-shaped gate that doesn't apply to it).
  - `ai-inference/src/ai_inference/gallery.py::get_current_production_
    model_version` now filters `model_kind = 'embedder'` explicitly, so a
    promoted LIVENESS model can never be picked up as if it were the
    embedder version.

Revision ID: c8f3a2e6d9b1
Revises: b2e6f9a1c4d7
Create Date: 2026-09-01 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c8f3a2e6d9b1"
down_revision: str | None = "b2e6f9a1c4d7"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

MODEL_KIND = postgresql.ENUM("embedder", "liveness", name="model_kind", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    MODEL_KIND.create(bind, checkfirst=True)

    op.add_column(
        "models",
        sa.Column(
            "model_kind",
            MODEL_KIND,
            nullable=False,
            server_default="embedder",
        ),
    )


def downgrade() -> None:
    op.drop_column("models", "model_kind")

    bind = op.get_bind()
    MODEL_KIND.drop(bind, checkfirst=True)
