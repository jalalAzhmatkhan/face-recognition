"""media_objects.session_id nullable for EVENT_FRAME rows (EC-TR-05, B-4)

`media_objects.session_id` has been `NOT NULL` (FK -> `enrollment_sessions`)
since the baseline schema, because until now every media row genuinely
belonged to exactly one enrollment session. `AccessEvent.frame_media_id`
(also since baseline) already points at this table, but
`app/services/retention_service.py`'s own docstring flagged the gap this
migration closes: "No code today actually inserts EVENT_FRAME rows -
`media_objects.session_id` is currently NOT NULL ... which is incompatible
with an EVENT_FRAME that has no enrollment session at all."

An EVENT_FRAME is a door-camera frame captured at *recognition* time (not
enrollment time) - it is not "media belonging to a session", it is a
free-standing artifact optionally linked back to the `access_events` row
that captured it (`AccessEvent.frame_media_id`, SET NULL on delete). This
migration makes `session_id` nullable so such a row is representable at
all: `session_id IS NULL` now means "this is an EVENT_FRAME, not
enrollment media" (`ai_training.db.dataset_repo`'s new `source=event_frame`
path relies on exactly this to distinguish the two, see EC-TR-05).

Purely additive/widening (NOT NULL -> nullable never invalidates an
existing row), and no code path writes a NULL session_id yet - actually
producing EVENT_FRAME rows (the upload/ingestion side) remains future work,
same as the retention_service.py docstring already anticipated.

Revision ID: b2e6f9a1c4d7
Revises: a1c8f4d0e7b3
Create Date: 2026-09-01 15:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b2e6f9a1c4d7"
down_revision: str | None = "a1c8f4d0e7b3"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "media_objects",
        "session_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )


def downgrade() -> None:
    # Would fail if any EVENT_FRAME row with a NULL session_id exists by
    # then - acceptable for a downgrade (the same tradeoff every other
    # NOT-NULL-tightening downgrade in this repo makes).
    op.alter_column(
        "media_objects",
        "session_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
