"""staff auth password hash

BE-03 (FR-USR-02, NFR-SEC-04): adds local email+password JWT auth for
`staff_accounts`, additive on top of the BE-02 baseline schema.

- Adds `password_hash` (nullable String) — argon2 hash, never plaintext.
- Relaxes `oidc_sub` to nullable: the baseline schema (f5f1daa8bc61) made it
  NOT NULL assuming OIDC-only signup, but BE-03 creates accounts via local
  password auth (bootstrap admin CLI / another admin) with no external OIDC
  subject yet. External OIDC federation remains a future phase — the column
  stays in the schema for that, just no longer mandatory. The existing unique
  index is preserved (Postgres unique indexes allow multiple NULLs).

Revision ID: 48b08e41d49a
Revises: 3a5b0a58f7ab
Create Date: 2026-08-30 15:59:32.798922

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "48b08e41d49a"
down_revision: str | None = "3a5b0a58f7ab"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("staff_accounts", sa.Column("password_hash", sa.String(255), nullable=True))
    op.alter_column("staff_accounts", "oidc_sub", existing_type=sa.String(255), nullable=True)


def downgrade() -> None:
    # Restoring NOT NULL on oidc_sub would fail if any password-only rows
    # exist (oidc_sub IS NULL) — that's expected/acceptable for a downgrade
    # of this feature, but it is not automatic; a DBA must backfill or accept
    # data loss on the rows themselves first if they want to reverse this.
    op.alter_column("staff_accounts", "oidc_sub", existing_type=sa.String(255), nullable=False)
    op.drop_column("staff_accounts", "password_hash")
