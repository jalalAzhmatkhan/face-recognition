"""ai_inference read-only role

Creates a new restricted Postgres role `ai_inference_ro` for the
`ai-inference` service (IN-03, least-privilege per TSD §6): `/recognize`'s
ANN gallery search needs to (1) find which model version is currently
`stage='PRODUCTION'` (table `models`) and (2) run the pgvector `<=>` search
against that version's templates (table `face_embeddings`). It needs NOTHING
else — no `users`/`staff_accounts`/`audit_logs`/etc — so this role is
narrower than `ai_training_ro` (migration `3a5b0a58f7ab`), which reads the
wider set of business tables for dataset building.

Follows the exact same pattern as `ai_training_ro`/`ai_training_embeddings_write`
in `3a5b0a58f7ab_db_role_separation.py`: a `NOLOGIN` role (no password here —
login credentials are provisioned/rotated out-of-band by a DBA/secret
manager), guarded by a `DO $$ ... $$` idempotency check since `CREATE ROLE
... IF NOT EXISTS` isn't supported.

Revision ID: b7c4e1a2d9f0
Revises: 7e2c4a91f3d0
Create Date: 2026-08-31 09:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7c4e1a2d9f0"
down_revision: str | None = "7e2c4a91f3d0"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

READ_ONLY_ROLE = "ai_inference_ro"

# Least privilege (TSD §6): ai-inference reads ONLY what /recognize's ANN
# search needs — the current PRODUCTION model version, and that version's
# gallery templates. No access to users/staff_accounts/audit_logs/etc.
READ_ONLY_TABLES = [
    "models",
    "face_embeddings",
]


def upgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{READ_ONLY_ROLE}') THEN
                CREATE ROLE {READ_ONLY_ROLE} NOLOGIN;
            END IF;
        END
        $$;
        """
    )

    op.execute(f"GRANT USAGE ON SCHEMA public TO {READ_ONLY_ROLE}")
    for table in READ_ONLY_TABLES:
        op.execute(f"GRANT SELECT ON {table} TO {READ_ONLY_ROLE}")


def downgrade() -> None:
    for table in reversed(READ_ONLY_TABLES):
        op.execute(f"REVOKE ALL ON {table} FROM {READ_ONLY_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {READ_ONLY_ROLE}")
    op.execute(f"DROP ROLE IF EXISTS {READ_ONLY_ROLE}")
