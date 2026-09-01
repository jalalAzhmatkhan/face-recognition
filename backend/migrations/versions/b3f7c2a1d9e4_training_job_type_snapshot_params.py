"""training_jobs job_type + snapshot_id + params (EC-BE-03,
TSD-edge-cases.md B-1/D-10)

Gelombang 1: formalizes job types beyond the one that already existed
(EVALUATION). Entirely additive except for relaxing `benchmark_id` to
nullable (see below) — no existing column is dropped, renamed, or
retyped.

`training_jobs`:
  - `job_type` (NOT NULL, new native enum `training_job_type`:
    `EVALUATION|FINETUNE_EMBEDDER|FINETUNE_LIVENESS|GALLERY_REEMBED|
    BACKFILL_MASKED_TEMPLATES`, DEFAULT `EVALUATION`) — every row that
    exists today was created by the only job-trigger path that has ever
    existed (`POST /training/jobs` -> `run_training_evaluation_job`), so
    backfilling every pre-EC-BE-03 row to `EVALUATION` via `server_default`
    on the same `ADD COLUMN` is exact, not a guess (same reasoning as
    EC-BE-02's `template_kind` backfill).
  - `benchmark_id` relaxed from NOT NULL to NULLable. Every row before this
    migration is an EVALUATION job, which always has one (unaffected), but
    the four new job types do not necessarily have a benchmark — whether a
    given type actually requires it is enforced at the API layer
    (`TrainingJobCreateRequest`'s per-type validator), not the DB schema,
    matching how `model_version` was already nullable here for the same
    reason.
  - `snapshot_id` (nullable, `varchar(64)`) — an S3 manifest id (UUID
    string) minted by `ai_training.data.snapshots.build_snapshot`. No
    `snapshots` table exists anywhere in this schema (snapshots are
    manifest-only in S3 per that module's docstring), so this is a loose
    reference by convention, not a `ForeignKey` — same pattern as
    `training_jobs.model_version` (see app/models/training_job.py
    docstring).
  - `params` (nullable, `jsonb`) — per-job-type configuration payload (e.g.
    `FINETUNE_EMBEDDER`'s `augmentations` list, `FINETUNE_LIVENESS`'s
    `dataset_ref`). NULL for every existing EVALUATION row, which never had
    a params payload.

Revision ID: b3f7c2a1d9e4
Revises: a4c7e0d1f9b2
Create Date: 2026-09-01 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b3f7c2a1d9e4"
down_revision: str | None = "a4c7e0d1f9b2"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

TRAINING_JOB_TYPE = postgresql.ENUM(
    "EVALUATION",
    "FINETUNE_EMBEDDER",
    "FINETUNE_LIVENESS",
    "GALLERY_REEMBED",
    "BACKFILL_MASKED_TEMPLATES",
    name="training_job_type",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    TRAINING_JOB_TYPE.create(bind, checkfirst=True)

    op.add_column(
        "training_jobs",
        sa.Column(
            "job_type",
            TRAINING_JOB_TYPE,
            nullable=False,
            server_default="EVALUATION",
        ),
    )

    op.alter_column(
        "training_jobs",
        "benchmark_id",
        existing_type=sa.String(length=255),
        nullable=True,
    )

    op.add_column(
        "training_jobs",
        sa.Column("snapshot_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "training_jobs",
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("training_jobs", "params")
    op.drop_column("training_jobs", "snapshot_id")

    op.alter_column(
        "training_jobs",
        "benchmark_id",
        existing_type=sa.String(length=255),
        nullable=False,
    )

    op.drop_column("training_jobs", "job_type")

    bind = op.get_bind()
    TRAINING_JOB_TYPE.drop(bind, checkfirst=True)
