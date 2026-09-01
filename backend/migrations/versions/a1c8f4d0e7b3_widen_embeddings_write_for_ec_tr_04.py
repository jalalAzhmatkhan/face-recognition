"""widen embeddings-write role for EC-TR-04 (D-4.4 high-similarity check)

EC-TR-04's high-similarity pair check runs inside the SAME ai-training
Celery worker as TR-03/TR-08 (`ai_training.similarity.high_similarity_check`,
called from `run_enrollment_qc_core` and `run_gallery_reembed_job_core`), at
the end of the embedding pipeline. Per TSD-edge-cases.md D-4.4, it needs to:

* SELECT `recognition_configs` (GLOBAL override lookup for tau) and
  INSERT/SELECT/UPDATE it (writing/tightening the `scope=user` override for
  a flagged pair). `ai_training_ro`'s `ALTER DEFAULT PRIVILEGES` grant
  (migration `3a5b0a58f7ab`) already covers plain SELECT for a read-only
  connection, but `ai_training_embeddings_write` -- the role this worker's
  single `settings.db.dsn` actually runs as (see `config.DBSettings`'s
  "KNOWN GAP" docstring, same accepted-gap pattern migration `09c300601b17`
  closed for TR-02/03) -- has no such default-privileges grant and needs
  INSERT/UPDATE explicitly, plus SELECT since this role's DSN is also what
  reads the GLOBAL override.
* INSERT `identity_similarity_flags` (this table's own model docstring:
  "written by the enrollment/re-embed pipeline ... not by this migration's
  own endpoints" -- EC-BE-04 anticipated this grant would need to follow
  once the pipeline side landed).
* SELECT `staff_accounts` -- to resolve an ADMIN account id to attribute an
  auto-generated `recognition_configs` override to (see
  `ai_training/src/ai_training/db/similarity_flags_repo.py
  ::get_system_staff_id`'s docstring for why: `created_by_staff_id` is
  `NOT NULL`/`RESTRICT` and there is no dedicated system/service staff
  concept in the schema yet -- flagged there as a known limitation, not
  fixed by this migration). `ai_training_ro` already has this via
  migration `3a5b0a58f7ab`'s explicit `READ_ONLY_TABLES` list, but again
  `ai_training_embeddings_write` does not.

Revision ID: a1c8f4d0e7b3
Revises: e1f9b3c7a2d5
Create Date: 2026-09-01 14:30:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1c8f4d0e7b3"
down_revision: str | None = "e1f9b3c7a2d5"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

EMBEDDINGS_WRITE_ROLE = "ai_training_embeddings_write"


def upgrade() -> None:
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE ON recognition_configs TO {EMBEDDINGS_WRITE_ROLE}"
    )
    op.execute(f"GRANT SELECT, INSERT ON identity_similarity_flags TO {EMBEDDINGS_WRITE_ROLE}")
    op.execute(f"GRANT SELECT ON staff_accounts TO {EMBEDDINGS_WRITE_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE SELECT ON staff_accounts FROM {EMBEDDINGS_WRITE_ROLE}")
    op.execute(f"REVOKE SELECT, INSERT ON identity_similarity_flags FROM {EMBEDDINGS_WRITE_ROLE}")
    op.execute(
        f"REVOKE SELECT, INSERT, UPDATE ON recognition_configs FROM {EMBEDDINGS_WRITE_ROLE}"
    )
