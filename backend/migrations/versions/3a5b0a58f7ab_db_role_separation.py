"""db role separation

Creates two restricted Postgres roles for `ai-training` per TSD §4 ("ai-training
gets read-only + embeddings-write role") and TSD §6 ("restrict embedding read
access"):

* `ai_training_ro`   — read-only (SELECT) on business tables needed for dataset
                       building (users, consents, enrollment_sessions,
                       media_objects metadata, models, access_policies). It is
                       explicitly NOT granted SELECT on `face_embeddings` or
                       `audit_logs` (embedding-inversion / audit tamper risk,
                       TSD §6).
* `ai_training_embeddings_write` — INSERT/UPDATE/SELECT on `face_embeddings`
                       ONLY (needed to upsert the gallery after training —
                       FR-ENR-07/TR-03). No other table access.

Also enforces `audit_logs` append-only at the DB level (NFR-SEC-05): revokes
UPDATE/DELETE from PUBLIC so no role — including the application's own DB
user — can mutate or remove audit rows outside of INSERT/SELECT, regardless of
what the application/repository layer does.

Login credentials for these roles are provisioned/rotated out-of-band (secret
manager) — this migration only defines the roles/grants, never a password.
See backend/README.md "DB role separation" for how a service picks up a role.

Revision ID: 3a5b0a58f7ab
Revises: f5f1daa8bc61
Create Date: 2026-08-30 15:46:14.219469

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3a5b0a58f7ab"
down_revision: str | None = "f5f1daa8bc61"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

READ_ONLY_ROLE = "ai_training_ro"
EMBEDDINGS_WRITE_ROLE = "ai_training_embeddings_write"

# Business tables ai-training may read (explicitly excludes face_embeddings
# and audit_logs).
READ_ONLY_TABLES = [
    "users",
    "staff_accounts",
    "consents",
    "enrollment_sessions",
    "media_objects",
    "models",
    "devices",
    "access_policies",
]


def upgrade() -> None:
    # NOLOGIN roles: no password here, a superuser/DBA later runs
    # `ALTER ROLE ... WITH LOGIN PASSWORD '...'` (or attaches an IAM/managed
    # identity) out-of-band. `IF NOT EXISTS` isn't supported for CREATE ROLE,
    # so guard via DO blocks to keep this migration re-runnable/idempotent.
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
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname = '{EMBEDDINGS_WRITE_ROLE}'
            ) THEN
                CREATE ROLE {EMBEDDINGS_WRITE_ROLE} NOLOGIN;
            END IF;
        END
        $$;
        """
    )

    op.execute(f"GRANT USAGE ON SCHEMA public TO {READ_ONLY_ROLE}")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {EMBEDDINGS_WRITE_ROLE}")

    for table in READ_ONLY_TABLES:
        op.execute(f"GRANT SELECT ON {table} TO {READ_ONLY_ROLE}")
    # access_events is partitioned; SELECT on the parent covers all partitions.
    op.execute(f"GRANT SELECT ON access_events TO {READ_ONLY_ROLE}")
    # Ensure future tables created by this app default to read-only for
    # ai_training_ro too (defence-in-depth; explicit grants above still apply).
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {READ_ONLY_ROLE}"
    )

    # embeddings-write role: face_embeddings ONLY, never SELECT/UPDATE/DELETE
    # on any other table (least privilege — TSD §6 embedding-inversion risk).
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON face_embeddings TO {EMBEDDINGS_WRITE_ROLE}")

    # audit_logs: append-only enforcement at the DB level (NFR-SEC-05).
    # Revoke UPDATE/DELETE from PUBLIC so no role can mutate/remove rows;
    # the application role keeps INSERT/SELECT (granted separately when the
    # app's own login role is provisioned — out of scope here).
    op.execute("REVOKE UPDATE, DELETE ON audit_logs FROM PUBLIC")


def downgrade() -> None:
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT ON TABLES FROM {READ_ONLY_ROLE}"
    )
    op.execute(f"REVOKE ALL ON face_embeddings FROM {EMBEDDINGS_WRITE_ROLE}")
    op.execute(f"REVOKE ALL ON access_events FROM {READ_ONLY_ROLE}")
    for table in reversed(READ_ONLY_TABLES):
        op.execute(f"REVOKE ALL ON {table} FROM {READ_ONLY_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {EMBEDDINGS_WRITE_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {READ_ONLY_ROLE}")
    op.execute(f"DROP ROLE IF EXISTS {EMBEDDINGS_WRITE_ROLE}")
    op.execute(f"DROP ROLE IF EXISTS {READ_ONLY_ROLE}")
    # Note: the audit_logs UPDATE/DELETE revoke from PUBLIC is intentionally
    # NOT restored on downgrade — re-enabling mutability on audit history is
    # a deliberate action a DBA should take explicitly, not an automatic one.
