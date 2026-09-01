"""model slice gate report (EC-QA-01)

Additive migration: adds `slice_gate_report` (nullable JSONB) to `models`,
so the ai-training worker can persist the EC-QA-01 per-slice
no-regression-bertoleransi-CI gate result (`SliceRegressionGateReport` -
see `ai_training/src/ai_training/evaluation/regression_gate.py`) alongside
the existing overall `recall`/`f1`/`precision`/`latency_ms_p95` columns it
already writes via `ai_training.db.training_job_repo.upsert_model_metrics`.

Same ownership split as those columns (see
`app/repositories/model_versions.py`'s module docstring): backend only
READS `slice_gate_report` (as an extra `promote_model` gate check,
FR-TRN-05/EC-QA-01); the ai-training worker is the only writer
(`ai_training.db.training_job_repo.upsert_model_slice_gate_report`), through
the same `ai_training_embeddings_write` role widened by migration
7e2c4a91f3d0 to cover `models`. No new grant needed — that role already has
UPDATE on this table's other metric columns.

`NULL` (the default, and the value for every row that existed before this
migration or was evaluated before EC-QA-01 shipped) means "no slice gate
report available for this candidate" - `promote_model` must treat that as
"nothing to check", never as an implicit pass OR fail, per EC-QA-01 task
instructions (a candidate must not be silently blocked just because the
harness has not produced per-slice data for it yet — see
`ai_training.evaluation.slices` module docstring on real edge-case data
being pending EC-OPS-02).

Revision ID: e5a9f2c1b3d6
Revises: b6d1f4a0c3e7
Create Date: 2026-09-01 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e5a9f2c1b3d6"
down_revision: str | None = "b6d1f4a0c3e7"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "models",
        sa.Column("slice_gate_report", postgresql.JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("models", "slice_gate_report")
