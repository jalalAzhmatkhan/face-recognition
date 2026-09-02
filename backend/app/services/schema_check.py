"""Is the database schema actually at the revision this code expects?

A pending migration does not announce itself. SQLAlchemy maps every column
the models declare, so the moment one of them is missing from the database,
ordinary requests start failing with an opaque 500 and a traceback only
visible in the server log — the endpoint that happens to touch the new
column first is blamed for a problem that has nothing to do with it. That
has now cost two separate debugging rounds on this project (the System
Parameter menu after `d1e5c8a3f7b2`, and `media/presign` after
`e4b9d2f6a8c3`), which is what this module exists to stop.

Deliberately NOT wired into `/healthz`: that endpoint is liveness, is used
by orchestrators to decide whether to restart the container, and must not
depend on the database. A schema mismatch is a READINESS problem — the
process is healthy, it just should not be serving traffic yet — so it lives
on `/readyz`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: The command an operator should run. Kept here so the API response and the
#: log line cannot drift apart.
UPGRADE_COMMAND = (
    "docker compose -f docker-compose.dev.yml --profile app run --rm backend-migrate"
)


@dataclass(frozen=True)
class SchemaStatus:
    """`applied`/`expected` are alembic revision ids, or `None` when they
    could not be determined (a brand-new database has no `alembic_version`
    row at all, which is itself a mismatch worth reporting)."""

    applied: str | None
    expected: str | None
    in_sync: bool
    detail: str


def expected_head(migrations_dir: Path | None = None) -> str | None:
    """The head revision of the migration scripts shipped with this code."""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        directory = migrations_dir or Path(__file__).resolve().parents[2] / "migrations"
        config = Config()
        config.set_main_option("script_location", str(directory))
        return ScriptDirectory.from_config(config).get_current_head()
    except Exception:  # noqa: BLE001 - a readiness probe must never raise
        logger.exception("schema_check.expected_head_unavailable")
        return None


def applied_revision(connection: Any) -> str | None:
    """The revision recorded in the database, or `None` if the database has
    never been migrated."""
    from alembic.runtime.migration import MigrationContext

    return MigrationContext.configure(connection).get_current_revision()


def check_schema(connection: Any, migrations_dir: Path | None = None) -> SchemaStatus:
    """Compare the two. Never raises: a readiness probe that blows up is
    strictly worse than one reporting that it could not tell."""
    expected = expected_head(migrations_dir)
    try:
        applied = applied_revision(connection)
    except Exception:  # noqa: BLE001 - see docstring
        logger.exception("schema_check.applied_revision_unavailable")
        return SchemaStatus(
            applied=None,
            expected=expected,
            in_sync=False,
            detail="Could not read the database's alembic revision.",
        )

    if expected is None:
        return SchemaStatus(
            applied=applied,
            expected=None,
            in_sync=False,
            detail="Could not determine the expected migration head from the shipped scripts.",
        )
    if applied is None:
        return SchemaStatus(
            applied=None,
            expected=expected,
            in_sync=False,
            detail=(
                f"Database has never been migrated (expected {expected}). Run: {UPGRADE_COMMAND}"
            ),
        )
    if applied != expected:
        return SchemaStatus(
            applied=applied,
            expected=expected,
            in_sync=False,
            detail=(
                f"Database is at {applied} but this build expects {expected}. "
                f"Pending migrations will surface as HTTP 500s on any endpoint touching a "
                f"new column. Run: {UPGRADE_COMMAND}"
            ),
        )
    return SchemaStatus(applied=applied, expected=expected, in_sync=True, detail="ok")
