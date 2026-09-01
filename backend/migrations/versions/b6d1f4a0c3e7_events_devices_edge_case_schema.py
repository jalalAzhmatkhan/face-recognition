"""access_events + devices edge-case schema (EC-BE-01, TSD-edge-cases.md D-1/D-10)

Foundational migration for the edge-case robustness design
(`documentation/tsd/TSD-edge-cases.md`) — every later edge-case task (D-2
liveness-per-mode, D-4 threshold multi-mode, D-5 per-device-class config,
D-7 benchmark slicing) reads the funnel-logging columns this migration
adds. Entirely additive; every new column is nullable (or has a safe
server-side default), so existing rows and existing callers of
`POST /access-events` / `POST /devices` stay valid untouched.

`access_events` (D-1, "PONDASI, kerjakan pertama"):
  - `condition_flags` (nullable JSONB) — per-frame condition signals at
    decision time (canonical keys: `masked`, `dark`, `blurry`, `low_res`,
    `sunglasses`; not a DB-level shape constraint, see
    app/schemas/access_events.py).
  - `reject_stage` (nullable, new native enum `reject_stage`:
    `detection|liveness|quality_gate|threshold|policy`) — which pipeline
    stage produced a non-GRANTED decision. NULL for GRANTED rows and for
    rows reported by a pre-EC-BE-01 caller.
  - `device_class` (nullable, new native enum `device_class`:
    `door_entry|attendance|unknown`) — denormalized copy of
    `devices.device_class` AT THE TIME OF THE EVENT, so monitoring queries
    never need to join `devices` and the historical value survives a later
    device reclassification.

`access_events` is a native-partitioned table (`PARTITION BY RANGE
(occurred_at)`, BE-02 baseline); `ALTER TABLE ... ADD COLUMN` on the parent
automatically cascades to every existing partition (same reasoning as
migrations/versions/d3b2e0a5c8f7_access_events_door_command_issued.py), so
no partition-by-partition migration is needed here.

`devices` (D-5/D-8):
  - `device_class` (NOT NULL, `device_class` enum, default `unknown`) —
    every existing device gets a safe, non-error classification rather
    than NULL; drives per-device-class recognition-policy resolution (a
    later task) and is the source `access_events.device_class` is
    denormalized from.
  - `commissioning_checklist` (nullable JSONB) — operator-filled
    camera-placement checklist (D-8: camera height, fill-light, WDR/HDR +
    AE-lock, shutter speed, stopping point, attendance-zone drawing). NULL
    = not commissioned yet. Loose jsonb blob, not DB-shape-constrained —
    see app/schemas/devices.py's docstring for the canonical field set and
    the note about syncing with `documentation/operations/
    camera-placement-guide.md` (EC-OPS-01) once that document exists.

Both new tables reuse the SAME `device_class` native enum type (created
once here, referenced by both `devices.device_class` and
`access_events.device_class`) — they describe the same category domain.

Revision ID: b6d1f4a0c3e7
Revises: f3a7c2e9b1d4
Create Date: 2026-09-01 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b6d1f4a0c3e7"
down_revision: str | None = "f3a7c2e9b1d4"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

DEVICE_CLASS = postgresql.ENUM(
    "door_entry", "attendance", "unknown", name="device_class", create_type=False
)
REJECT_STAGE = postgresql.ENUM(
    "detection",
    "liveness",
    "quality_gate",
    "threshold",
    "policy",
    name="reject_stage",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    DEVICE_CLASS.create(bind, checkfirst=True)
    REJECT_STAGE.create(bind, checkfirst=True)

    op.add_column(
        "devices",
        sa.Column(
            "device_class",
            DEVICE_CLASS,
            nullable=False,
            server_default="unknown",
        ),
    )
    op.add_column(
        "devices", sa.Column("commissioning_checklist", postgresql.JSONB, nullable=True)
    )

    op.add_column(
        "access_events", sa.Column("condition_flags", postgresql.JSONB, nullable=True)
    )
    op.add_column(
        "access_events",
        sa.Column("reject_stage", REJECT_STAGE, nullable=True),
    )
    op.add_column(
        "access_events",
        sa.Column("device_class", DEVICE_CLASS, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("access_events", "device_class")
    op.drop_column("access_events", "reject_stage")
    op.drop_column("access_events", "condition_flags")

    op.drop_column("devices", "commissioning_checklist")
    op.drop_column("devices", "device_class")

    bind = op.get_bind()
    REJECT_STAGE.drop(bind, checkfirst=True)
    DEVICE_CLASS.drop(bind, checkfirst=True)
