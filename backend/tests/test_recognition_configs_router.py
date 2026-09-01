"""Integration tests for `/api/v1/recognition-configs/*` via FastAPI
TestClient (EC-BE-04, TSD-edge-cases.md D-4.2/D-10, OQ-6).

No real DB: every repository dependency is overridden with an in-memory
fake, `get_current_staff` is overridden directly — mirrors
test_access_policies_router.py.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.dependencies.auth import CurrentStaff, get_current_staff
from app.main import create_app
from app.models.enums import StaffRole
from app.models.recognition_config import RecognitionConfig
from app.routers.recognition_configs import (
    get_audit_log_repository,
    get_recognition_config_repository,
)


class FakeRecognitionConfigRepository:
    def __init__(self, configs: list[RecognitionConfig] | None = None) -> None:
        self._by_id: dict[uuid.UUID, RecognitionConfig] = {c.id: c for c in (configs or [])}

    def get(self, config_id: uuid.UUID) -> RecognitionConfig | None:
        return self._by_id.get(config_id)

    def get_by_key(self, *, scope, scope_ref, mode) -> RecognitionConfig | None:
        for config in self._by_id.values():
            if config.scope == scope and config.scope_ref == scope_ref and config.mode == mode:
                return config
        return None

    def list(self, *, scope=None, scope_ref=None, mode=None, limit=100, offset=0):
        items = list(self._by_id.values())
        if scope is not None:
            items = [c for c in items if c.scope == scope]
        if scope_ref is not None:
            items = [c for c in items if c.scope_ref == scope_ref]
        if mode is not None:
            items = [c for c in items if c.mode == mode]
        items.sort(key=lambda c: (c.scope.value, c.mode))
        return items[offset : offset + limit]

    def count(self, *, scope=None, scope_ref=None, mode=None) -> int:
        return len(self.list(scope=scope, scope_ref=scope_ref, mode=mode, limit=10**9, offset=0))

    def create(self, config: RecognitionConfig) -> RecognitionConfig:
        config.id = config.id or uuid.uuid4()
        now = datetime.now(UTC)
        config.created_at = now
        config.updated_at = now
        self._by_id[config.id] = config
        return config

    def update(self, config: RecognitionConfig) -> RecognitionConfig:
        config.updated_at = datetime.now(UTC)
        self._by_id[config.id] = config
        return config

    def delete(self, config: RecognitionConfig) -> None:
        self._by_id.pop(config.id, None)


class FakeAuditLogRepository:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def record(self, *, actor: str, action: str, entity: str, payload=None):
        entry = {"actor": actor, "action": action, "entity": entity, "payload": payload}
        self.entries.append(entry)
        return entry


def _make_config(
    *, scope, scope_ref=None, mode="normal", similarity_threshold=0.5, **kwargs
) -> RecognitionConfig:
    now = datetime.now(UTC)
    return RecognitionConfig(
        id=uuid.uuid4(),
        scope=scope,
        scope_ref=scope_ref,
        mode=mode,
        similarity_threshold=similarity_threshold,
        margin=kwargs.get("margin"),
        liveness_threshold=kwargs.get("liveness_threshold"),
        min_frames=kwargs.get("min_frames"),
        created_by_staff_id=uuid.uuid4(),
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def config_repo() -> FakeRecognitionConfigRepository:
    from app.models.enums import RecognitionConfigScope

    return FakeRecognitionConfigRepository(
        [
            _make_config(scope=RecognitionConfigScope.GLOBAL, mode="normal"),
            _make_config(
                scope=RecognitionConfigScope.DEVICE_CLASS,
                scope_ref="attendance",
                mode="masked",
                similarity_threshold=0.4,
            ),
        ]
    )


@pytest.fixture
def audit_repo() -> FakeAuditLogRepository:
    return FakeAuditLogRepository()


def _client(
    config_repo: FakeRecognitionConfigRepository,
    audit_repo: FakeAuditLogRepository,
    role: StaffRole,
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_recognition_config_repository] = lambda: config_repo
    app.dependency_overrides[get_audit_log_repository] = lambda: audit_repo
    app.dependency_overrides[get_current_staff] = lambda: CurrentStaff(
        id=uuid.uuid4(), email=f"{role.value.lower()}@example.com", role=role
    )
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def admin_client(config_repo, audit_repo) -> TestClient:
    return _client(config_repo, audit_repo, StaffRole.ADMIN)


@pytest.fixture
def operator_client(config_repo, audit_repo) -> TestClient:
    return _client(config_repo, audit_repo, StaffRole.OPERATOR)


@pytest.fixture
def viewer_client(config_repo, audit_repo) -> TestClient:
    return _client(config_repo, audit_repo, StaffRole.VIEWER)


# --- GET /recognition-configs (list) ----------------------------------------


def test_list_allowed_for_admin(admin_client: TestClient) -> None:
    response = admin_client.get("/api/v1/recognition-configs")
    assert response.status_code == 200
    assert response.json()["total"] == 2


def test_list_allowed_for_operator(operator_client: TestClient) -> None:
    response = operator_client.get("/api/v1/recognition-configs")
    assert response.status_code == 200


def test_list_allowed_for_viewer(viewer_client: TestClient) -> None:
    """VIEWER read-only per EC-BE-04 acceptance criteria — read is allowed."""
    response = viewer_client.get("/api/v1/recognition-configs")
    assert response.status_code == 200
    assert response.json()["total"] == 2


def test_list_requires_authentication() -> None:
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/v1/recognition-configs")
    assert response.status_code == 401


def test_list_filters_by_scope_and_mode(admin_client: TestClient) -> None:
    response = admin_client.get(
        "/api/v1/recognition-configs", params={"scope": "device_class", "mode": "masked"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["scope_ref"] == "attendance"


# --- POST /recognition-configs (create) -------------------------------------


def test_create_denied_for_operator(operator_client: TestClient) -> None:
    response = operator_client.post(
        "/api/v1/recognition-configs",
        json={"scope": "global", "mode": "dark", "similarity_threshold": 0.3},
    )
    assert response.status_code == 403


def test_create_denied_for_viewer(viewer_client: TestClient) -> None:
    """VIEWER read-only — write is forbidden."""
    response = viewer_client.post(
        "/api/v1/recognition-configs",
        json={"scope": "global", "mode": "dark", "similarity_threshold": 0.3},
    )
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")


def test_create_succeeds_for_admin(
    admin_client: TestClient, audit_repo: FakeAuditLogRepository
) -> None:
    response = admin_client.post(
        "/api/v1/recognition-configs",
        json={"scope": "global", "mode": "dark", "similarity_threshold": 0.3},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["scope"] == "global"
    assert body["scope_ref"] is None
    assert body["mode"] == "dark"
    assert body["similarity_threshold"] == 0.3
    assert any(e["action"] == "recognition_config.create" for e in audit_repo.entries)


def test_create_rejects_global_scope_with_scope_ref(admin_client: TestClient) -> None:
    response = admin_client.post(
        "/api/v1/recognition-configs",
        json={
            "scope": "global",
            "scope_ref": "something",
            "mode": "dark",
            "similarity_threshold": 0.3,
        },
    )
    assert response.status_code == 422


def test_create_rejects_device_class_scope_without_scope_ref(admin_client: TestClient) -> None:
    response = admin_client.post(
        "/api/v1/recognition-configs",
        json={"scope": "device_class", "mode": "dark", "similarity_threshold": 0.3},
    )
    assert response.status_code == 422


def test_create_rejects_all_fields_null(admin_client: TestClient) -> None:
    response = admin_client.post(
        "/api/v1/recognition-configs",
        json={"scope": "global", "mode": "dark"},
    )
    assert response.status_code == 422


def test_create_rejects_duplicate_key(admin_client: TestClient) -> None:
    """Duplicate (scope, scope_ref, mode) -> 409, not a 500/second row."""
    response = admin_client.post(
        "/api/v1/recognition-configs",
        json={"scope": "global", "mode": "normal", "similarity_threshold": 0.6},
    )
    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")


def test_create_allows_same_mode_different_scope_ref(admin_client: TestClient) -> None:
    """Same mode, different scope_ref -> not a duplicate."""
    response = admin_client.post(
        "/api/v1/recognition-configs",
        json={
            "scope": "device_class",
            "scope_ref": "door_entry",
            "mode": "masked",
            "similarity_threshold": 0.55,
        },
    )
    assert response.status_code == 201


# --- PATCH /recognition-configs/{id} ----------------------------------------


def test_update_succeeds_for_admin(
    admin_client: TestClient, config_repo: FakeRecognitionConfigRepository
) -> None:
    config_id = next(iter(config_repo._by_id))
    response = admin_client.patch(
        f"/api/v1/recognition-configs/{config_id}", json={"similarity_threshold": 0.75}
    )
    assert response.status_code == 200
    assert response.json()["similarity_threshold"] == 0.75


def test_update_can_clear_a_field_to_null(
    admin_client: TestClient, config_repo: FakeRecognitionConfigRepository
) -> None:
    config_id = next(
        c.id for c in config_repo._by_id.values() if c.similarity_threshold == 0.4
    )
    response = admin_client.patch(
        f"/api/v1/recognition-configs/{config_id}", json={"similarity_threshold": None}
    )
    assert response.status_code == 200
    assert response.json()["similarity_threshold"] is None


def test_update_denied_for_operator(
    operator_client: TestClient, config_repo: FakeRecognitionConfigRepository
) -> None:
    config_id = next(iter(config_repo._by_id))
    response = operator_client.patch(
        f"/api/v1/recognition-configs/{config_id}", json={"similarity_threshold": 0.75}
    )
    assert response.status_code == 403


def test_update_denied_for_viewer(
    viewer_client: TestClient, config_repo: FakeRecognitionConfigRepository
) -> None:
    config_id = next(iter(config_repo._by_id))
    response = viewer_client.patch(
        f"/api/v1/recognition-configs/{config_id}", json={"similarity_threshold": 0.75}
    )
    assert response.status_code == 403


def test_update_returns_404_for_unknown_id(admin_client: TestClient) -> None:
    response = admin_client.patch(
        f"/api/v1/recognition-configs/{uuid.uuid4()}", json={"similarity_threshold": 0.75}
    )
    assert response.status_code == 404


def test_update_writes_audit_entry(
    admin_client: TestClient,
    config_repo: FakeRecognitionConfigRepository,
    audit_repo: FakeAuditLogRepository,
) -> None:
    config_id = next(iter(config_repo._by_id))
    response = admin_client.patch(
        f"/api/v1/recognition-configs/{config_id}", json={"margin": 0.02}
    )
    assert response.status_code == 200
    assert any(e["action"] == "recognition_config.update" for e in audit_repo.entries)


# --- DELETE /recognition-configs/{id} ---------------------------------------


def test_delete_removes_row_for_admin(
    admin_client: TestClient, config_repo: FakeRecognitionConfigRepository
) -> None:
    config_id = next(iter(config_repo._by_id))
    response = admin_client.delete(f"/api/v1/recognition-configs/{config_id}")
    assert response.status_code == 204
    assert config_repo.get(config_id) is None


def test_delete_denied_for_operator(
    operator_client: TestClient, config_repo: FakeRecognitionConfigRepository
) -> None:
    config_id = next(iter(config_repo._by_id))
    response = operator_client.delete(f"/api/v1/recognition-configs/{config_id}")
    assert response.status_code == 403


def test_delete_denied_for_viewer(
    viewer_client: TestClient, config_repo: FakeRecognitionConfigRepository
) -> None:
    config_id = next(iter(config_repo._by_id))
    response = viewer_client.delete(f"/api/v1/recognition-configs/{config_id}")
    assert response.status_code == 403


def test_delete_returns_404_for_unknown_id(admin_client: TestClient) -> None:
    response = admin_client.delete(f"/api/v1/recognition-configs/{uuid.uuid4()}")
    assert response.status_code == 404


def test_delete_writes_audit_entry(
    admin_client: TestClient,
    config_repo: FakeRecognitionConfigRepository,
    audit_repo: FakeAuditLogRepository,
) -> None:
    config_id = next(iter(config_repo._by_id))
    response = admin_client.delete(f"/api/v1/recognition-configs/{config_id}")
    assert response.status_code == 204
    assert any(e["action"] == "recognition_config.delete" for e in audit_repo.entries)
