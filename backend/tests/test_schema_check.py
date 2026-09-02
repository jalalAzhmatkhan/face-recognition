"""`schema_check` + `/readyz`.

The point of these is operability, not correctness of the schema itself: a
database behind the code's migration head breaks arbitrary endpoints with
opaque 500s, and this is what turns that into one legible answer.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services import schema_check

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


def test_expected_head_reads_the_shipped_migration_scripts() -> None:
    head = schema_check.expected_head(MIGRATIONS_DIR)
    assert head is not None
    assert len(head) >= 8


def test_in_sync_when_the_database_matches_the_shipped_head() -> None:
    head = schema_check.expected_head(MIGRATIONS_DIR)
    with patch.object(schema_check, "applied_revision", return_value=head):
        result = schema_check.check_schema(MagicMock(), MIGRATIONS_DIR)

    assert result.in_sync is True
    assert result.applied == head


def test_a_behind_database_names_both_revisions_and_the_fix() -> None:
    with patch.object(schema_check, "applied_revision", return_value="d1e5c8a3f7b2"):
        result = schema_check.check_schema(MagicMock(), MIGRATIONS_DIR)

    assert result.in_sync is False
    assert "d1e5c8a3f7b2" in result.detail
    # The operator should not have to go looking for the command.
    assert schema_check.UPGRADE_COMMAND in result.detail


def test_a_never_migrated_database_is_reported_as_such() -> None:
    with patch.object(schema_check, "applied_revision", return_value=None):
        result = schema_check.check_schema(MagicMock(), MIGRATIONS_DIR)

    assert result.in_sync is False
    assert "never been migrated" in result.detail


def test_check_schema_never_raises_when_the_revision_cannot_be_read() -> None:
    # A readiness probe that throws is strictly worse than one reporting it
    # could not tell.
    with patch.object(schema_check, "applied_revision", side_effect=RuntimeError("boom")):
        result = schema_check.check_schema(MagicMock(), MIGRATIONS_DIR)

    assert result.in_sync is False
    assert result.applied is None


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


def test_healthz_does_not_touch_the_database(client: TestClient) -> None:
    """Liveness must stay up even when the database is down — otherwise a
    database blip gets the container restarted, which fixes nothing."""
    with patch("app.routers.health.get_engine", side_effect=RuntimeError("db down")):
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readyz_reports_503_and_the_fix_when_the_schema_is_behind(
    client: TestClient,
) -> None:
    behind = schema_check.SchemaStatus(
        applied="d1e5c8a3f7b2",
        expected="e4b9d2f6a8c3",
        in_sync=False,
        detail=f"Database is at d1e5c8a3f7b2 ... Run: {schema_check.UPGRADE_COMMAND}",
    )
    with (
        patch("app.routers.health.get_engine"),
        patch("app.routers.health.schema_check.check_schema", return_value=behind),
    ):
        response = client.get("/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["schema_in_sync"] is False
    assert body["schema_applied_revision"] == "d1e5c8a3f7b2"
    assert body["schema_expected_revision"] == "e4b9d2f6a8c3"
    assert schema_check.UPGRADE_COMMAND in body["detail"]


def test_readyz_reports_503_when_the_database_is_unreachable(client: TestClient) -> None:
    with patch("app.routers.health.get_engine", side_effect=RuntimeError("db down")):
        response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["database"] == "unreachable"


def test_readyz_is_200_when_everything_matches(client: TestClient) -> None:
    ok = schema_check.SchemaStatus(
        applied="e4b9d2f6a8c3", expected="e4b9d2f6a8c3", in_sync=True, detail="ok"
    )
    with (
        patch("app.routers.health.get_engine"),
        patch("app.routers.health.schema_check.check_schema", return_value=ok),
    ):
        response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
