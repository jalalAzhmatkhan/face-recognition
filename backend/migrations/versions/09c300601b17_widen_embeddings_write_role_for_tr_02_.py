"""widen embeddings-write role for TR-02/03 worker

TR-02 (QC worker) and TR-03 (embedding extraction) run in ai-training's own
Celery worker (see ai-training/src/ai_training/worker/), consuming the same
`run_enrollment_qc` task name backend's stub registers (BE-07). That worker
needs more than `ai_training_embeddings_write`'s original `face_embeddings`-
only grant (migration 3a5b0a58f7ab):

* SELECT + UPDATE on `enrollment_sessions` -- to read the current state for
  idempotency (only proceed while QC_RUNNING) and to write the state
  transitions (QC_RUNNING -> QC_PASSED/REJECTED_QUALITY -> EMBEDDING ->
  ENROLLED) plus the `qc_report` jsonb column.
* SELECT on `media_objects` -- to look up the finalized video/photo S3 keys
  for the session before running QC. Found live: the original migration
  only anticipated `enrollment_sessions`/`audit_logs`; a real worker run
  against Postgres failed with `permission denied for table media_objects`
  until this was added too.
* INSERT on `audit_logs` -- to record `job.*`/`enrollment.*` audit entries
  the same way backend's own worker does (BE-07/BE-08 pattern). Append-only
  is still enforced: UPDATE/DELETE on `audit_logs` stays revoked from
  PUBLIC (migration 3a5b0a58f7ab) and this migration does not touch that.

This was flagged as a real gap during TR-02/03 implementation rather than
silently worked around with a superuser connection -- see
ai-training/README.md.

Revision ID: 09c300601b17
Revises: bcf250963057
Create Date: 2026-08-30 19:10:23.128905

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "09c300601b17"
down_revision: str | None = "bcf250963057"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

EMBEDDINGS_WRITE_ROLE = "ai_training_embeddings_write"


def upgrade() -> None:
    op.execute(f"GRANT SELECT, UPDATE ON enrollment_sessions TO {EMBEDDINGS_WRITE_ROLE}")
    op.execute(f"GRANT SELECT ON media_objects TO {EMBEDDINGS_WRITE_ROLE}")
    op.execute(f"GRANT INSERT ON audit_logs TO {EMBEDDINGS_WRITE_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE INSERT ON audit_logs FROM {EMBEDDINGS_WRITE_ROLE}")
    op.execute(f"REVOKE SELECT ON media_objects FROM {EMBEDDINGS_WRITE_ROLE}")
    op.execute(f"REVOKE SELECT, UPDATE ON enrollment_sessions FROM {EMBEDDINGS_WRITE_ROLE}")
