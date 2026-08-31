"""ai_inference_ro: grant SELECT on devices (IN-02)

IN-02 closes the "no authentication at all" gap on `POST /recognize`
documented in IN-03 (`ai_inference/main.py`'s old endpoint docstring):
device-facing requests to `ai-inference` now must present a bearer token of
the form `<credential_id>.<secret>`, verified the same way BE-09's
`get_current_device` verifies it for backend-facing device routes (parse ->
look up by `auth_credential_ref` -> Argon2id-verify `credential_hash` ->
reject if `status = 'DISABLED'`).

To do that lookup+verify, `ai-inference` needs to read `devices.
auth_credential_ref`, `devices.credential_hash`, and `devices.status` using
its existing `ai_inference_ro` role (created in `b7c4e1a2d9f0` for the
`/recognize` gallery search: SELECT on `models` + `face_embeddings`). This
migration widens that SAME role with a SELECT grant on `devices` only --
still least-privilege: SELECT-only (no INSERT/UPDATE/DELETE -- device
credential issuance/rotation/disablement stays backend-only, via
`staff_accounts`-authenticated routes), whole-table (not column-level,
consistent with every other grant in this project -- see `b7c4e1a2d9f0` and
`3a5b0a58f7ab`), and no other table.

Revision ID: d4e8a2f6c1b9
Revises: b7c4e1a2d9f0
Create Date: 2026-08-31 10:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e8a2f6c1b9"
down_revision: str | None = "b7c4e1a2d9f0"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

READ_ONLY_ROLE = "ai_inference_ro"
NEW_TABLE = "devices"


def upgrade() -> None:
    op.execute(f"GRANT SELECT ON {NEW_TABLE} TO {READ_ONLY_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON {NEW_TABLE} FROM {READ_ONLY_ROLE}")
