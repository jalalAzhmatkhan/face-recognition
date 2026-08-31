"""password reset tokens

BE-03 follow-up (forgot-password flow): a single-use token minted per
`POST /auth/forgot-password` request and consumed by `POST /auth/reset-password`.

Mirrors the `<id>.<secret>` scheme already used for device credentials
(migration a1c9f3d8e2b4) — `id` here is just the row's own primary key
(each token is single-use, minted fresh per request, so no separate
non-secret lookup column is needed the way `devices.auth_credential_ref`
needs one to survive rotation), and `token_hash` is an Argon2id hash of the
secret half, never the plaintext.

Revision ID: f3a7c2e9b1d4
Revises: d4e8a2f6c1b9
Create Date: 2026-08-31 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f3a7c2e9b1d4"
down_revision: str | None = "d4e8a2f6c1b9"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "staff_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("staff_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_password_reset_tokens_staff_id", "password_reset_tokens", ["staff_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_password_reset_tokens_staff_id", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
