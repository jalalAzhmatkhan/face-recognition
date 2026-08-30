"""device credential hash + rotation timestamp

BE-09 (FR-USR-04, NFR-SEC-04): adds per-device token credential support on
top of the `devices` table from the BE-02 baseline schema (f5f1daa8bc61).

- `auth_credential_ref` already existed as the non-secret credential
  reference; this migration makes it UNIQUE (it now doubles as the
  "credential id" half of the issued `<credential_id>.<secret>` device
  token, so two devices must never share one).
- Adds `credential_hash` (nullable String) — Argon2id hash of the secret
  half (mirrors `staff_accounts.password_hash`, migration
  48b08e41d49a). Never the plaintext secret.
- Adds `credential_rotated_at` (nullable DateTime) — when the credential
  currently on file was issued/rotated.

Both new columns are nullable: existing rows (none expected in practice,
since no device has been registered through the API before BE-09 shipped)
simply have no credential until registered/rotated through the new
`POST /devices` / `POST /devices/{id}/rotate-credential` endpoints.

Revision ID: a1c9f3d8e2b4
Revises: 09c300601b17
Create Date: 2026-08-30 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1c9f3d8e2b4"
down_revision: str | None = "09c300601b17"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("credential_hash", sa.String(255), nullable=True))
    op.add_column(
        "devices", sa.Column("credential_rotated_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_unique_constraint(
        "uq_devices_auth_credential_ref", "devices", ["auth_credential_ref"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_devices_auth_credential_ref", "devices", type_="unique")
    op.drop_column("devices", "credential_rotated_at")
    op.drop_column("devices", "credential_hash")
