"""users.reenroll_due + reenroll_due_reason + reenroll_due_marked_at
(EC-BE-05, TSD-edge-cases.md A-5/D-9)

Additive columns on `users` only — no existing column/table is touched.

Design decision (EC-BE-05 task instructions: "users? enrollment_sessions?"):
placed on `users`, not `enrollment_sessions`, because the flag is a property
of the IDENTITY ("this person needs to redo enrollment"), not of any one
enrollment attempt — a user has zero-or-more enrollment sessions over time,
and the two criteria that set this flag (enrollment age, moving-average
genuine-match score from `access_events`) are both scoped to the user, not
to a single session row. It also matches the two independent producers of
this flag: this migration's own Celery Beat job (`app/services/
reenroll_due_service.py`), AND a documented future caller from
`ai-training`'s masked-template backfill job (D-4.5/EC-TR-03) when a user's
enrollment video has already left the 90-day retention window and can't be
used to backfill a masked template — that job flags the same per-user
concept for a different reason, via direct SQL against this same column
(ai-training has no access to backend's ORM/services), so a single
per-user column (rather than a per-session one) is the shape both callers
need.

No new "last enrolled at" column: the anchor for the age criterion is the
MOST RECENT `enrollment_sessions.updated_at` among that user's `ENROLLED`
sessions — same anchor-timestamp convention already used by
`app/services/retention_service.py` (BE-14) for "when did this user finish
enrolling", so this migration does not duplicate that timestamp.

Columns:
  - `reenroll_due BOOLEAN NOT NULL DEFAULT false` — the flag itself,
    surfaced in the enrollment-management UI (TSD A-5).
  - `reenroll_due_reason VARCHAR(64) NULL` — short machine code for why the
    flag was set (this task writes `enrollment_age` and/or
    `low_genuine_score`, joined with `+` if both apply in the same run;
    EC-TR-03's future caller is expected to write
    `video_retention_expired`). Free-text-ish on purpose (not a native
    enum) since more reasons may be added by later, independent callers
    without a migration.
  - `reenroll_due_marked_at TIMESTAMPTZ NULL` — when the flag was set, for
    UI display / staleness checks. NOT touched again once `reenroll_due` is
    already true (see the service's idempotency contract — re-running the
    job is a no-op for an already-flagged user, by design, so this
    timestamp reflects the ORIGINAL marking, not the most recent job run).

Revision ID: d8e1f3a6c2b5
Revises: c7d4b1a9e3f6
Create Date: 2026-09-01 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d8e1f3a6c2b5"
down_revision: str | None = "c7d4b1a9e3f6"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "reenroll_due",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "users",
        sa.Column("reenroll_due_reason", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("reenroll_due_marked_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Supports the beat job's "which users are already flagged" filter
    # (skip-for-idempotency) without a full table scan.
    op.create_index(
        "ix_users_reenroll_due",
        "users",
        ["reenroll_due"],
        postgresql_where=sa.text("reenroll_due IS TRUE"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_users_reenroll_due",
        table_name="users",
        postgresql_where=sa.text("reenroll_due IS TRUE"),
    )
    op.drop_column("users", "reenroll_due_marked_at")
    op.drop_column("users", "reenroll_due_reason")
    op.drop_column("users", "reenroll_due")
