"""Integration tests for `/api/v1/system-parameters/*` via FastAPI
TestClient.

No real DB: the repository dependency is overridden with an in-memory
fake, `get_current_staff` is overridden directly — mirrors
test_recognition_configs_router.py.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.dependencies.auth import CurrentStaff, get_current_staff
from app.main import create_app
from app.models.enums import StaffRole
from app.models.system_parameter import SystemParameter
from app.routers.system_parameters import get_audit_log_repository, get_system_parameter_repository
from app.services.system_parameter_service import DEFAULT_ENROLLMENT_QUALITY


class FakeSystemParameterRepository:
    def __init__(self, rows: list[SystemParameter] | None = None) -> None:
        self._by_key: dict[str, SystemParameter] = {r.key: r for r in (rows or [])}

    def get(self, key: str) -> SystemParameter | None:
        return self._by_key.get(key)

    def upsert(self, key: str, value: dict, *, updated_by: uuid.UUID) -> SystemParameter:
        row = self._by_key.get(key)
        if row is None:
            row = SystemParameter(key=key, value=value, updated_by=updated_by)
        else:
            row.value = value
            row.updated_by = updated_by
        row.updated_at = datetime.now(UTC)
        self._by_key[key] = row
        return row


class FakeAuditLogRepository:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def record(self, *, actor: str, action: str, entity: str, payload=None):
        entry = {"actor": actor, "action": action, "entity": entity, "payload": payload}
        self.entries.append(entry)
        return entry


@pytest.fixture
def param_repo() -> FakeSystemParameterRepository:
    return FakeSystemParameterRepository()


@pytest.fixture
def audit_repo() -> FakeAuditLogRepository:
    return FakeAuditLogRepository()


def _client(
    param_repo: FakeSystemParameterRepository,
    audit_repo: FakeAuditLogRepository,
    role: StaffRole,
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_system_parameter_repository] = lambda: param_repo
    app.dependency_overrides[get_audit_log_repository] = lambda: audit_repo
    app.dependency_overrides[get_current_staff] = lambda: CurrentStaff(
        id=uuid.uuid4(), email=f"{role.value.lower()}@example.com", role=role
    )
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def admin_client(param_repo, audit_repo) -> TestClient:
    return _client(param_repo, audit_repo, StaffRole.ADMIN)


@pytest.fixture
def operator_client(param_repo, audit_repo) -> TestClient:
    return _client(param_repo, audit_repo, StaffRole.OPERATOR)


@pytest.fixture
def viewer_client(param_repo, audit_repo) -> TestClient:
    return _client(param_repo, audit_repo, StaffRole.VIEWER)


# --- GET /system-parameters/enrollment-quality ------------------------------


def test_get_returns_built_in_defaults_when_no_row_saved_yet(admin_client: TestClient) -> None:
    response = admin_client.get("/api/v1/system-parameters/enrollment-quality")
    assert response.status_code == 200
    body = response.json()
    assert body["min_blur_variance"] == DEFAULT_ENROLLMENT_QUALITY.min_blur_variance
    assert body["min_brightness"] == DEFAULT_ENROLLMENT_QUALITY.min_brightness
    assert body["max_brightness"] == DEFAULT_ENROLLMENT_QUALITY.max_brightness
    assert body["is_default"] is True
    assert body["updated_by"] is None
    assert body["updated_at"] is None


def test_get_allowed_for_operator_and_viewer(
    operator_client: TestClient, viewer_client: TestClient
) -> None:
    assert operator_client.get("/api/v1/system-parameters/enrollment-quality").status_code == 200
    assert viewer_client.get("/api/v1/system-parameters/enrollment-quality").status_code == 200


def test_get_reflects_a_previously_saved_override(
    admin_client: TestClient, param_repo: FakeSystemParameterRepository
) -> None:
    staff_id = uuid.uuid4()
    param_repo.upsert(
        "enrollment_capture_quality",
        {"min_blur_variance": 25.0, "min_brightness": 30.0, "max_brightness": 230.0},
        updated_by=staff_id,
    )
    response = admin_client.get("/api/v1/system-parameters/enrollment-quality")
    assert response.status_code == 200
    body = response.json()
    assert body["min_blur_variance"] == 25.0
    assert body["is_default"] is False
    assert body["updated_by"] == str(staff_id)


# --- PUT /system-parameters/enrollment-quality ------------------------------


def test_put_denied_for_operator_and_viewer(
    operator_client: TestClient, viewer_client: TestClient
) -> None:
    body = {"min_blur_variance": 20.0, "min_brightness": 30.0, "max_brightness": 230.0}
    assert (
        operator_client.put("/api/v1/system-parameters/enrollment-quality", json=body).status_code
        == 403
    )
    assert (
        viewer_client.put("/api/v1/system-parameters/enrollment-quality", json=body).status_code
        == 403
    )


def test_put_saves_and_get_reflects_the_new_values(
    admin_client: TestClient, audit_repo: FakeAuditLogRepository
) -> None:
    body = {"min_blur_variance": 20.0, "min_brightness": 30.0, "max_brightness": 230.0}
    response = admin_client.put("/api/v1/system-parameters/enrollment-quality", json=body)
    assert response.status_code == 200
    saved = response.json()
    assert saved["min_blur_variance"] == 20.0
    assert saved["is_default"] is False

    follow_up = admin_client.get("/api/v1/system-parameters/enrollment-quality")
    assert follow_up.json()["min_blur_variance"] == 20.0

    assert any(e["action"] == "system_parameter.update" for e in audit_repo.entries)


def test_put_rejects_min_brightness_not_below_max_brightness(admin_client: TestClient) -> None:
    body = {"min_blur_variance": 20.0, "min_brightness": 230.0, "max_brightness": 230.0}
    response = admin_client.put("/api/v1/system-parameters/enrollment-quality", json=body)
    assert response.status_code == 422


def test_put_rejects_non_positive_blur_variance(admin_client: TestClient) -> None:
    body = {"min_blur_variance": 0, "min_brightness": 30.0, "max_brightness": 230.0}
    response = admin_client.put("/api/v1/system-parameters/enrollment-quality", json=body)
    assert response.status_code == 422


def test_put_rejects_brightness_out_of_0_255_range(admin_client: TestClient) -> None:
    body = {"min_blur_variance": 20.0, "min_brightness": -5.0, "max_brightness": 230.0}
    response = admin_client.put("/api/v1/system-parameters/enrollment-quality", json=body)
    assert response.status_code == 422


def test_get_requires_authentication() -> None:
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/v1/system-parameters/enrollment-quality")
    assert response.status_code == 401
