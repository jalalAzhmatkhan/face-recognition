"""access_events.door_command_issued (BE-10, TSD §2.2/§4, FR-INF-05)

Adds the EFFECTIVE-door-decision audit column described in
app/models/access_event.py — distinct from the existing `decision` column
(the raw inference result). A row can have `decision=GRANTED` yet
`door_command_issued=false` (fail-secure: policy cache miss, a
SUSPENDED/OFFBOARDED user, no matching door_group policy, or outside the
policy's valid_from/valid_to window — see
app/services/access_event_service.py).

`access_events` is a native-partitioned table (`PARTITION BY RANGE
(occurred_at)`, BE-02 baseline); `ALTER TABLE ... ADD COLUMN` on the parent
automatically cascades to every existing partition, so no partition-by-
partition migration is needed here.

Backfill: existing rows (none expected in practice before BE-10 ships, same
reasoning as migrations/versions/a1c9f3d8e2b4_device_credential_hash.py)
get `false` via `server_default`, matching the ORM model's Python-side
default.

Revision ID: d3b2e0a5c8f7
Revises: c2a1f9d4b7e6
Create Date: 2026-08-30 22:05:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d3b2e0a5c8f7"
down_revision: str | None = "c2a1f9d4b7e6"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "access_events",
        sa.Column(
            "door_command_issued",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("access_events", "door_command_issued")
