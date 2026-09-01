"""Integration tests for `/api/v1/devices/*` via FastAPI TestClient (BE-09).

No real DB: `get_device_repository`/`get_audit_log_repository` are
overridden with in-memory fakes, and `get_current_staff` is overridden
directly to avoid re-deriving the whole JWT login flow for every RBAC
scenario (mirrors the fake-repository pattern established in
test_users_router.py). Device-authenticated endpoints (heartbeat) go
through the real `device_service.authenticate_device` logic against the
fake repository, so those tests exercise the actual Argon2 verify path
rather than overriding `get_current_device` directly.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.dependencies.auth import CurrentStaff, get_current_staff
from app.dependencies.device_auth import get_device_repository as get_device_repository_auth
from app.main import create_app
from app.models.device import Device
from app.models.enums import DeviceStatus, StaffRole
from app.routers.devices import get_audit_log_repository, get_device_repository


class FakeDeviceRepository:
    def __init__(self, devices: list[Device] | None = None) -> None:
        self._by_id: dict[uuid.UUID, Device] = {d.id: d for d in (devices or [])}

    def get(self, device_id: uuid.UUID) -> Device | None:
        return self._by_id.get(device_id)

    def get_by_credential_id(self, credential_id: str) -> Device | None:
        for d in self._by_id.values():
            if d.auth_credential_ref == credential_id:
                return d
        return None

    def list(
        self,
        *,
        status: DeviceStatus | None = None,
        door_group: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Device]:
        items = list(self._by_id.values())
        if status is not None:
            items = [d for d in items if d.status == status]
        if door_group is not None:
            items = [d for d in items if d.door_group == door_group]
        items.sort(key=lambda d: d.name)
        return items[offset : offset + limit]

    def count(self, *, status: DeviceStatus | None = None, door_group: str | None = None) -> int:
        items = list(self._by_id.values())
        if status is not None:
            items = [d for d in items if d.status == status]
        if door_group is not None:
            items = [d for d in items if d.door_group == door_group]
        return len(items)

    def create(self, device: Device) -> Device:
        device.id = device.id or uuid.uuid4()
        self._by_id[device.id] = device
        return device

    def update(self, device: Device) -> Device:
        self._by_id[device.id] = device
        return device


class FakeAuditLogRepository:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def record(self, *, actor: str, action: str, entity: str, payload=None):
        entry = {"actor": actor, "action": action, "entity": entity, "payload": payload}
        self.entries.append(entry)
        return entry


def _make_device(name: str, door_group: str, status: DeviceStatus = DeviceStatus.OFFLINE) -> Device:
    return Device(
        id=uuid.uuid4(),
        name=name,
        door_group=door_group,
        auth_credential_ref=f"seed-{uuid.uuid4().hex[:8]}",
        credential_hash=None,
        credential_rotated_at=None,
        last_heartbeat_at=None,
        status=status,
    )


@pytest.fixture
def device_repo() -> FakeDeviceRepository:
    return FakeDeviceRepository(
        [
            _make_device("Front Door", "main-entrance"),
            _make_device("Back Door", "loading-dock", DeviceStatus.DISABLED),
        ]
    )


@pytest.fixture
def audit_repo() -> FakeAuditLogRepository:
    return FakeAuditLogRepository()


def _client(
    device_repo: FakeDeviceRepository, audit_repo: FakeAuditLogRepository, role: StaffRole
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_device_repository] = lambda: device_repo
    # Heartbeat's device-auth dependency resolves its own repository
    # instance (app/dependencies/device_auth.py) — override that one too so
    # both routes see the same fake backing store.
    app.dependency_overrides[get_device_repository_auth] = lambda: device_repo
    app.dependency_overrides[get_audit_log_repository] = lambda: audit_repo
    app.dependency_overrides[get_current_staff] = lambda: CurrentStaff(
        id=uuid.uuid4(), email=f"{role.value.lower()}@example.com", role=role
    )
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def admin_client(device_repo, audit_repo) -> TestClient:
    return _client(device_repo, audit_repo, StaffRole.ADMIN)


@pytest.fixture
def operator_client(device_repo, audit_repo) -> TestClient:
    return _client(device_repo, audit_repo, StaffRole.OPERATOR)


@pytest.fixture
def viewer_client(device_repo, audit_repo) -> TestClient:
    return _client(device_repo, audit_repo, StaffRole.VIEWER)


# --- GET /devices (list) -------------------------------------------------


def test_list_devices_returns_all_for_admin(admin_client: TestClient) -> None:
    response = admin_client.get("/api/v1/devices")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2


def test_list_devices_allowed_for_operator(operator_client: TestClient) -> None:
    response = operator_client.get("/api/v1/devices")
    assert response.status_code == 200


def test_list_devices_denied_for_viewer(viewer_client: TestClient) -> None:
    response = viewer_client.get("/api/v1/devices")
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")


def test_list_devices_requires_authentication() -> None:
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/v1/devices")
    assert response.status_code == 401


def test_list_devices_filters_by_status(admin_client: TestClient) -> None:
    response = admin_client.get("/api/v1/devices", params={"status": "DISABLED"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Back Door"


def test_list_devices_filters_by_door_group(admin_client: TestClient) -> None:
    response = admin_client.get("/api/v1/devices", params={"door_group": "main-entrance"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Front Door"


def test_device_with_no_heartbeat_is_stale(admin_client: TestClient, device_repo) -> None:
    front_door = next(d for d in device_repo._by_id.values() if d.name == "Front Door")
    response = admin_client.get(f"/api/v1/devices/{front_door.id}")
    assert response.status_code == 200
    assert response.json()["is_stale"] is True


def test_disabled_device_is_never_stale(admin_client: TestClient, device_repo) -> None:
    back_door = next(d for d in device_repo._by_id.values() if d.name == "Back Door")
    response = admin_client.get(f"/api/v1/devices/{back_door.id}")
    assert response.status_code == 200
    assert response.json()["is_stale"] is False


# --- POST /devices (register) --------------------------------------------


def test_register_device_returns_credential_once(
    admin_client: TestClient, audit_repo: FakeAuditLogRepository
) -> None:
    response = admin_client.post(
        "/api/v1/devices", json={"name": "Side Door", "door_group": "warehouse"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Side Door"
    assert body["status"] == "OFFLINE"
    assert "." in body["credential"]
    # Never leaked into the audit trail.
    assert all(
        "credential" not in (e["payload"] or {})
        for e in audit_repo.entries
        if e["action"] == "device.register"
    )
    assert any(e["action"] == "device.register" for e in audit_repo.entries)


def test_register_device_denied_for_operator(operator_client: TestClient) -> None:
    response = operator_client.post(
        "/api/v1/devices", json={"name": "Nope Door", "door_group": "x"}
    )
    assert response.status_code == 403


def test_register_device_denied_for_viewer(viewer_client: TestClient) -> None:
    response = viewer_client.post(
        "/api/v1/devices", json={"name": "Nope Door 2", "door_group": "x"}
    )
    assert response.status_code == 403


def test_register_device_rejects_blank_name(admin_client: TestClient) -> None:
    response = admin_client.post("/api/v1/devices", json={"name": "", "door_group": "x"})
    assert response.status_code == 422


# --- EC-BE-01: device_class / commissioning_checklist ----------------------


def test_register_device_without_device_class_defaults_to_unknown(
    admin_client: TestClient,
) -> None:
    """Backward-compatible: a caller that predates EC-BE-01 doesn't send
    `device_class` at all and still gets a valid, non-error response."""
    response = admin_client.post(
        "/api/v1/devices", json={"name": "Legacy Caller Door", "door_group": "legacy"}
    )
    assert response.status_code == 201
    assert response.json()["device_class"] == "unknown"
    assert response.json()["commissioning_checklist"] is None


def test_register_device_with_device_class_and_checklist(admin_client: TestClient) -> None:
    checklist = {
        "camera_height_m": 1.55,
        "fill_light_installed": True,
        "shutter_speed_ok": True,
        "attendance_zone_drawn": True,
        "commissioned_by": "ops-team",
    }
    response = admin_client.post(
        "/api/v1/devices",
        json={
            "name": "Absensi Panel A",
            "door_group": "absensi",
            "device_class": "attendance",
            "commissioning_checklist": checklist,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["device_class"] == "attendance"
    assert body["commissioning_checklist"] == checklist


def test_register_device_rejects_invalid_device_class(admin_client: TestClient) -> None:
    response = admin_client.post(
        "/api/v1/devices",
        json={"name": "Bad Class Door", "door_group": "x", "device_class": "not_a_class"},
    )
    assert response.status_code == 422


def test_update_device_class_and_checklist_succeeds_for_admin(
    admin_client: TestClient, device_repo
) -> None:
    existing_id = next(iter(device_repo._by_id))
    response = admin_client.patch(
        f"/api/v1/devices/{existing_id}",
        json={
            "device_class": "door_entry",
            "commissioning_checklist": {"camera_height_m": 1.6, "backlight_avoided": True},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["device_class"] == "door_entry"
    assert body["commissioning_checklist"] == {
        "camera_height_m": 1.6,
        "backlight_avoided": True,
    }


# --- POST /devices/{id}/heartbeat (device-authenticated) -----------------


def _register(admin_client: TestClient, name: str = "Heartbeat Door") -> dict:
    response = admin_client.post("/api/v1/devices", json={"name": name, "door_group": "hb-group"})
    assert response.status_code == 201
    return response.json()


def test_heartbeat_with_valid_credential_marks_online(admin_client: TestClient) -> None:
    device = _register(admin_client)
    response = admin_client.post(
        f"/api/v1/devices/{device['id']}/heartbeat",
        headers={"Authorization": f"Bearer {device['credential']}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ONLINE"
    assert body["last_heartbeat_at"] is not None


def test_heartbeat_with_invalid_credential_is_401(admin_client: TestClient) -> None:
    device = _register(admin_client)
    response = admin_client.post(
        f"/api/v1/devices/{device['id']}/heartbeat",
        headers={"Authorization": "Bearer bogus.credential"},
    )
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")


def test_heartbeat_with_missing_credential_is_401(admin_client: TestClient) -> None:
    device = _register(admin_client)
    response = admin_client.post(f"/api/v1/devices/{device['id']}/heartbeat")
    assert response.status_code == 401


def test_heartbeat_wrong_secret_for_known_credential_id_is_401(admin_client: TestClient) -> None:
    device = _register(admin_client)
    credential_id = device["credential"].split(".", 1)[0]
    response = admin_client.post(
        f"/api/v1/devices/{device['id']}/heartbeat",
        headers={"Authorization": f"Bearer {credential_id}.totally-wrong-secret"},
    )
    assert response.status_code == 401


def test_heartbeat_for_disabled_device_is_403(admin_client: TestClient) -> None:
    device = _register(admin_client, name="Disable Me")
    disable_resp = admin_client.patch(
        f"/api/v1/devices/{device['id']}", json={"status": "DISABLED"}
    )
    assert disable_resp.status_code == 200
    response = admin_client.post(
        f"/api/v1/devices/{device['id']}/heartbeat",
        headers={"Authorization": f"Bearer {device['credential']}"},
    )
    assert response.status_code == 403


def test_heartbeat_path_id_must_match_credential_owner(admin_client: TestClient) -> None:
    device_a = _register(admin_client, name="Door A")
    device_b = _register(admin_client, name="Door B")
    response = admin_client.post(
        f"/api/v1/devices/{device_b['id']}/heartbeat",
        headers={"Authorization": f"Bearer {device_a['credential']}"},
    )
    assert response.status_code == 403


# --- POST /devices/{id}/rotate-credential ---------------------------------


def test_rotate_credential_invalidates_old_token(admin_client: TestClient) -> None:
    device = _register(admin_client, name="Rotate Me")
    old_credential = device["credential"]

    rotate_resp = admin_client.post(f"/api/v1/devices/{device['id']}/rotate-credential")
    assert rotate_resp.status_code == 200
    new_credential = rotate_resp.json()["credential"]
    assert new_credential != old_credential

    old_heartbeat = admin_client.post(
        f"/api/v1/devices/{device['id']}/heartbeat",
        headers={"Authorization": f"Bearer {old_credential}"},
    )
    assert old_heartbeat.status_code == 401

    new_heartbeat = admin_client.post(
        f"/api/v1/devices/{device['id']}/heartbeat",
        headers={"Authorization": f"Bearer {new_credential}"},
    )
    assert new_heartbeat.status_code == 200


def test_rotate_credential_denied_for_operator(
    admin_client: TestClient, operator_client: TestClient
) -> None:
    device = _register(admin_client, name="Rotate Guard")
    response = operator_client.post(f"/api/v1/devices/{device['id']}/rotate-credential")
    assert response.status_code == 403


def test_rotate_credential_returns_404_for_unknown_id(admin_client: TestClient) -> None:
    response = admin_client.post(f"/api/v1/devices/{uuid.uuid4()}/rotate-credential")
    assert response.status_code == 404


# --- PATCH /devices/{id} ---------------------------------------------------


def test_update_device_name_succeeds_for_admin(admin_client: TestClient, device_repo) -> None:
    existing_id = next(iter(device_repo._by_id))
    response = admin_client.patch(f"/api/v1/devices/{existing_id}", json={"name": "Renamed"})
    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"


def test_update_device_denied_for_operator(operator_client: TestClient, device_repo) -> None:
    existing_id = next(iter(device_repo._by_id))
    response = operator_client.patch(f"/api/v1/devices/{existing_id}", json={"name": "Nope"})
    assert response.status_code == 403


def test_update_device_returns_404_for_unknown_id(admin_client: TestClient) -> None:
    response = admin_client.patch(f"/api/v1/devices/{uuid.uuid4()}", json={"name": "Ghost"})
    assert response.status_code == 404


def test_update_device_rejects_invalid_status_enum(admin_client: TestClient, device_repo) -> None:
    existing_id = next(iter(device_repo._by_id))
    response = admin_client.patch(f"/api/v1/devices/{existing_id}", json={"status": "NOT_A_STATUS"})
    assert response.status_code == 422


# --- DELETE /devices/{id} (alias for DISABLED) -----------------------------


def test_delete_device_disables_instead_of_hard_delete(
    admin_client: TestClient, device_repo, audit_repo: FakeAuditLogRepository
) -> None:
    existing_id = next(iter(device_repo._by_id))
    response = admin_client.delete(f"/api/v1/devices/{existing_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "DISABLED"
    assert device_repo.get(existing_id) is not None
    assert any(e["action"] == "device.update" for e in audit_repo.entries)


def test_delete_device_denied_for_operator(operator_client: TestClient, device_repo) -> None:
    existing_id = next(iter(device_repo._by_id))
    response = operator_client.delete(f"/api/v1/devices/{existing_id}")
    assert response.status_code == 403


def test_delete_device_returns_404_for_unknown_id(admin_client: TestClient) -> None:
    response = admin_client.delete(f"/api/v1/devices/{uuid.uuid4()}")
    assert response.status_code == 404
