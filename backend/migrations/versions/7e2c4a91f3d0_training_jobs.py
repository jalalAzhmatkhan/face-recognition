"""training_jobs table (BE-13, FR-TRN-02/03)

Adds the `training_jobs` table backing `POST/GET /api/v1/training/jobs`
(model trigger + status polling). `model_version` is intentionally NOT a
real `ForeignKey("models.version")` — see app/models/training_job.py's
module docstring: a job is created before any `models` row for that
candidate version necessarily exists.

Also extends the `ai_training_embeddings_write` role (migrations
3a5b0a58f7ab / 09c300601b17) with `SELECT, INSERT, UPDATE` on the new
`training_jobs` table AND on the pre-existing `models` table — the
ai-training worker (`ai_training.worker.tasks.run_training_evaluation_job`,
BE-13) needs to update job status/error/mlflow_run_id as it runs, and to
upsert the `models` row with metrics once `evaluate_candidate` finishes.
`models` had no write grant for this role before now (BE-02/TR-07 only ever
read it indirectly via MLflow, never via this DB role) — granted here
deliberately, up front, rather than left as a gap to discover live (unlike
09c300601b17's `media_objects`/`enrollment_sessions` grants, which WERE
found live after the fact).

Revision ID: 7e2c4a91f3d0
Revises: d3b2e0a5c8f7
Create Date: 2026-08-31 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "7e2c4a91f3d0"
down_revision: str | None = "d3b2e0a5c8f7"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

EMBEDDINGS_WRITE_ROLE = "ai_training_embeddings_write"

TRAINING_JOB_STATUS = postgresql.ENUM(
    "PENDING", "RUNNING", "SUCCEEDED", "FAILED", name="training_job_status", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    TRAINING_JOB_STATUS.create(bind, checkfirst=True)

    op.create_table(
        "training_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("model_version", sa.String(64), nullable=True),
        sa.Column("benchmark_id", sa.String(255), nullable=False),
        sa.Column(
            "status",
            TRAINING_JOB_STATUS,
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column(
            "triggered_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("staff_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("mlflow_run_id", sa.String(255), nullable=True),
    )
    op.create_index("ix_training_jobs_status", "training_jobs", ["status"])
    op.create_index("ix_training_jobs_model_version", "training_jobs", ["model_version"])

    # ai-training worker write-back (see module docstring).
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON training_jobs TO {EMBEDDINGS_WRITE_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON models TO {EMBEDDINGS_WRITE_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE SELECT, INSERT, UPDATE ON models FROM {EMBEDDINGS_WRITE_ROLE}")
    op.execute(f"REVOKE SELECT, INSERT, UPDATE ON training_jobs FROM {EMBEDDINGS_WRITE_ROLE}")
    op.drop_index("ix_training_jobs_model_version", table_name="training_jobs")
    op.drop_index("ix_training_jobs_status", table_name="training_jobs")
    op.drop_table("training_jobs")
    bind = op.get_bind()
    TRAINING_JOB_STATUS.drop(bind, checkfirst=True)
