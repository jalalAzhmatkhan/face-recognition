"""BE-02 schema tests.

IMPORTANT LIMITATION: there is no live Postgres+pgvector instance in this test
environment, so these tests deliberately do NOT open a real database
connection. They instead verify two things that catch the vast majority of
schema-authoring mistakes without one:

1. Import-level correctness: every ORM model in `app/models/` imports cleanly
   and registers itself on `Base.metadata` with the columns/keys TSD §4
   describes (catches typos, bad FK targets, duplicate table names, etc.).
2. Alembic SQL-generation correctness: `alembic upgrade head --sql` (offline
   mode) renders the *entire* migration chain to raw SQL text without needing
   a DBAPI connection. This exercises the exact DDL that would run against a
   real database — CREATE EXTENSION, enum types, every table/FK/index, the
   HNSW index, the partitioned access_events table + example partitions, and
   the role-separation grants — and fails loudly on any SQLAlchemy/alembic
   authoring error (bad SQL syntax inside `op.execute`, wrong operator
   ordering, etc.).

What this does NOT verify (needs a real Postgres 16 + pgvector, e.g. via
`docker compose -f docker-compose.dev.yml up postgres` then
`uv run alembic upgrade head` against it — see backend/README.md):
    - that the extension `vector` actually installs on the target Postgres,
    - that the HNSW index actually builds (syntax is correct, but index
      build behavior/params should be eyeballed once against real pgvector),
    - that the partition routing works for real inserts,
    - that the granted roles behave as expected end-to-end (SELECT succeeds
      on read-only tables, is denied on face_embeddings/audit_logs mutation,
      embeddings-write role can INSERT into face_embeddings only),
    - `alembic downgrade -1` / roundtrip against a real database.
"""

import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

EXPECTED_TABLES = {
    "users",
    "staff_accounts",
    "consents",
    "enrollment_sessions",
    "media_objects",
    "face_embeddings",
    "models",
    "devices",
    "access_policies",
    "access_events",
    "audit_logs",
}


def test_all_models_import_and_register_metadata() -> None:
    from app.models import Base

    table_names = set(Base.metadata.tables.keys())
    missing = EXPECTED_TABLES - table_names
    assert not missing, f"tables missing from metadata: {missing}"


def test_users_table_matches_tsd_columns() -> None:
    from app.models import Base

    columns = set(Base.metadata.tables["users"].columns.keys())
    assert columns == {
        "id",
        "external_ref",
        "full_name",
        "status",
        "created_at",
        "updated_at",
    }


def test_face_embeddings_vector_column_dimension() -> None:
    from pgvector.sqlalchemy import Vector

    from app.models import EMBEDDING_DIM, Base

    vector_col = Base.metadata.tables["face_embeddings"].columns["vector"]
    assert isinstance(vector_col.type, Vector)
    assert EMBEDDING_DIM == 512


def test_access_events_is_partitioned_with_composite_pk() -> None:
    from app.models import Base

    table = Base.metadata.tables["access_events"]
    assert table.dialect_options["postgresql"]["partition_by"] == "RANGE (occurred_at)"
    pk_columns = {c.name for c in table.primary_key.columns}
    assert pk_columns == {"id", "occurred_at"}


def test_access_events_has_ec_be_01_funnel_logging_columns() -> None:
    """EC-BE-01 (TSD-edge-cases.md D-1/D-10): additive funnel-logging
    columns on `access_events` — condition_flags, reject_stage,
    device_class."""
    from app.models import Base

    columns = Base.metadata.tables["access_events"].columns
    for name in ("condition_flags", "reject_stage", "device_class"):
        assert name in columns
        assert columns[name].nullable is True


def test_devices_has_ec_be_01_device_class_and_checklist_columns() -> None:
    """EC-BE-01 (TSD-edge-cases.md D-5/D-8/D-10): devices.device_class is
    NOT NULL (safe `unknown` default for pre-existing devices);
    commissioning_checklist is nullable jsonb."""
    from app.models import Base

    columns = Base.metadata.tables["devices"].columns
    assert "device_class" in columns
    assert columns["device_class"].nullable is False
    assert "commissioning_checklist" in columns
    assert columns["commissioning_checklist"].nullable is True


def test_audit_logs_repository_layer_exposes_no_update_delete() -> None:
    """No repository module may expose UPDATE/DELETE for audit_logs (NFR-SEC-05).

    BE-02 doesn't ship an AuditLog repository yet, but this guards the
    invariant for whoever adds one later (BE-12).
    """
    import app.repositories as repositories_pkg

    assert not hasattr(repositories_pkg, "AuditLogRepository") or all(
        name not in dir(repositories_pkg.AuditLogRepository)
        for name in ("update", "delete")
    )


def test_alembic_upgrade_head_sql_dry_run_renders_full_chain() -> None:
    """Render the whole migration chain to SQL offline (no DB connection).

    This is the closest thing to "alembic upgrade head bersih" (BE-02
    acceptance criterion) achievable without a live Postgres+pgvector — see
    module docstring for what still needs manual verification.
    """
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    sql = result.stdout
    assert "CREATE EXTENSION IF NOT EXISTS vector" in sql
    assert "USING hnsw (vector vector_cosine_ops)" in sql
    assert "PARTITION BY RANGE (occurred_at)" in sql
    assert "CREATE TABLE access_events_2026_08 PARTITION OF access_events" in sql
    assert "CREATE ROLE ai_training_ro NOLOGIN" in sql
    assert "CREATE ROLE ai_training_embeddings_write NOLOGIN" in sql
    assert "REVOKE UPDATE, DELETE ON audit_logs FROM PUBLIC" in sql
    for table in EXPECTED_TABLES:
        assert f"CREATE TABLE {table}" in sql or f"CREATE TABLE {table} (" in sql

    # EC-BE-01 (TSD-edge-cases.md D-1/D-10): additive events+devices schema.
    assert "CREATE TYPE device_class AS ENUM" in sql
    assert "CREATE TYPE reject_stage AS ENUM" in sql
    assert "ALTER TABLE devices ADD COLUMN device_class" in sql
    assert "ALTER TABLE devices ADD COLUMN commissioning_checklist" in sql
    assert "ALTER TABLE access_events ADD COLUMN condition_flags" in sql
    assert "ALTER TABLE access_events ADD COLUMN reject_stage" in sql
    assert "ALTER TABLE access_events ADD COLUMN device_class" in sql


def test_alembic_downgrade_full_sql_dry_run_renders_cleanly() -> None:
    """Symmetric check: the full downgrade chain also renders without error."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "head:base", "--sql"],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "DROP TABLE users" in result.stdout
    assert "DROP EXTENSION IF EXISTS vector" in result.stdout
