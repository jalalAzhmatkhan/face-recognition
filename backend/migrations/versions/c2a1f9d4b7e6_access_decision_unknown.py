"""access_decision UNKNOWN value (BE-10, FR-INF-02)

FR-INF-02 requires a distinct "no confident match found" outcome from a
recognition attempt, separate from `SPOOF_SUSPECTED` (liveness/anti-spoof
concern) — the existing `access_decision` enum only had
`GRANTED`/`DENIED`/`SPOOF_SUSPECTED` (BE-02 baseline), so this adds
`UNKNOWN`.

This is an additive `ALTER TYPE ... ADD VALUE`, NOT a type recreation (which
would require dropping/recreating every column that uses it). It is safe to
run inside a normal transactional migration on Postgres 12+ (this project
targets pg16 — see docker-compose.dev.yml's `pgvector/pgvector:pg16` image)
as long as the newly added value is not USED (inserted or compared against)
in the SAME transaction that adds it. Neither this migration nor any other
migration chained after it in the same `alembic upgrade` invocation
references `'UNKNOWN'`, so the default transactional DDL wrapping
(migrations/env.py's `context.begin_transaction()`) is safe here — no
`COMMIT`/autocommit-block workaround is needed.

`ADD VALUE IF NOT EXISTS` makes this idempotent/re-runnable.

Downgrade is a documented no-op: Postgres has no `ALTER TYPE ... DROP
VALUE`. Removing a single enum value would require recreating the whole
type under a temporary name and rewriting every dependent column/index —
disproportionate risk versus leaving an unused `UNKNOWN` member behind on a
downgrade, and no code path writes `UNKNOWN` once the application is rolled
back past this revision anyway.

Revision ID: c2a1f9d4b7e6
Revises: a1c9f3d8e2b4
Create Date: 2026-08-30 22:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c2a1f9d4b7e6"
down_revision: str | None = "a1c9f3d8e2b4"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE access_decision ADD VALUE IF NOT EXISTS 'UNKNOWN'")


def downgrade() -> None:
    # No-op — see module docstring: Postgres cannot drop a single enum
    # value without recreating the entire type.
    pass
