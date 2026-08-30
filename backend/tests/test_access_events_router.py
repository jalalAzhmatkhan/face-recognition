"""Integration tests for `/api/v1/access-events/*` via FastAPI TestClient
(BE-10, FR-INF-01..06, FR-MON-01).

No real DB/Redis: every repository dependency is overridden with an
in-memory fake, `get_current_staff` is overridden directly for the
staff-read endpoint (mirrors test_users_router.py), and device
authentication for the ingest endpoint goes through the REAL
`device_service.authenticate_device` logic against a fake `DeviceRepository`
(mirrors test_devices_router.py's heartbeat tests) — so these tests also
exercise the actual Argon2 verify path, not a bypassed dependency override.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.redis_client import get_redis_client
from app.dependencies.auth import CurrentStaff, get_current_staff
from app.dependencies.device_auth import get_device_repository as get_device_repository_auth
from app.main import create_app
from app.models.access_event import AccessEvent
from app.models.access_policy import AccessPolicy
from app.models.device import Device
from app.models.enums import AccessDecision, DeviceStatus, StaffRole, UserStatus
from app.models.user import User
from app.routers.access_events import (
    get_access_event_repository,
    get_access_policy_repository,
    get_user_repository,
)
from app.routers.devices import (
    get_audit_log_repository as get_device_audit_log_repository,
)
from app.routers.devices import (
    get_device_repository as get_device_repository_devices,
)


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

    def list(self, **_kwargs) -> list[Device]:
        return list(self._by_id.values())

    def count(self, **_kwargs) -> int:
        return len(self._by_id)

    def create(self, device: Device) -> Device:
        device.id = device.id or uuid.uuid4()
        self._by_id[device.id] = device
        return device

    def update(self, device: Device) -> Device:
        self._by_id[device.id] = device
        return device


class FakeDeviceAuditLogRepository:
    def record(self, **_kwargs):
        return None


class FakeAccessEventRepository:
    def __init__(self) -> None:
        self.events: list[AccessEvent] = []

    def create(self, event: AccessEvent) -> AccessEvent:
        event.id = event.id or uuid.uuid4()
        if event.occurred_at is None:
            event.occurred_at = datetime.now(UTC)
        self.events.append(event)
        return event

    def list(
        self,
        *,
        device_id=None,
        decision=None,
        occurred_from=None,
        occurred_to=None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AccessEvent]:
        items = list(self.events)
        if device_id is not None:
            items = [e for e in items if e.device_id == device_id]
        if decision is not None:
            items = [e for e in items if e.decision == decision]
        if occurred_from is not None:
            items = [e for e in items if e.occurred_at >= occurred_from]
        if occurred_to is not None:
            items = [e for e in items if e.occurred_at <= occurred_to]
        items.sort(key=lambda e: e.occurred_at, reverse=True)
        return items[offset : offset + limit]

    def count(self, **filters) -> int:
        return len(self.list(**filters, limit=10**9, offset=0))


class FakeAccessPolicyRepository:
    def __init__(self, policies: list[AccessPolicy] | None = None) -> None:
        self._policies = list(policies or [])

    def list_for_user(self, user_id: uuid.UUID) -> list[AccessPolicy]:
        return [p for p in self._policies if p.user_id == user_id]


class FakeUserRepository:
    def __init__(self, users: list[User] | None = None) -> None:
        self._by_id: dict[uuid.UUID, User] = {u.id: u for u in (users or [])}

    def get(self, user_id: uuid.UUID) -> User | None:
        return self._by_id.get(user_id)


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, name: str):
        return self.store.get(name)

    def set(self, name: str, value: str, ex=None):
        self.store[name] = value
        return True

    def delete(self, name: str):
        return 1 if self.store.pop(name, None) is not None else 0


def _make_device(door_group: str = "main-entrance") -> Device:
    return Device(
        id=uuid.uuid4(),
        name="Front Door",
        door_group=door_group,
        auth_credential_ref=f"seed-{uuid.uuid4().hex[:8]}",
        credential_hash=None,
        credential_rotated_at=None,
        last_heartbeat_at=None,
        status=DeviceStatus.ONLINE,
    )


def _make_user(status: UserStatus = UserStatus.ACTIVE) -> User:
    now = datetime.now(UTC)
    return User(
        id=uuid.uuid4(),
        external_ref=f"EMP-{uuid.uuid4().hex[:6]}",
        full_name="Test Person",
        status=status,
        created_at=now,
        updated_at=now,
    )


def _make_policy(
    *, user_id: uuid.UUID, door_group: str, allowed: bool = True, valid_from=None, valid_to=None
) -> AccessPolicy:
    return AccessPolicy(
        id=uuid.uuid4(),
        user_id=user_id,
        group_id=None,
        door_group=door_group,
        allowed=allowed,
        valid_from=valid_from,
        valid_to=valid_to,
    )


def _cache_snapshot_json(*, status: UserStatus, policies: list[AccessPolicy]) -> str:
    """Hand-assemble the exact JSON app/services/policy_cache.py would have
    written, so tests can seed a cache HIT without going through a real
    refresh_cache() DB round trip."""
    import json as _json

    return _json.dumps(
        {
            "status": status.value,
            "policies": [
                {
                    "door_group": p.door_group,
                    "allowed": p.allowed,
                    "valid_from": p.valid_from.isoformat() if p.valid_from else None,
                    "valid_to": p.valid_to.isoformat() if p.valid_to else None,
                }
                for p in policies
            ],
        }
    )


@pytest.fixture
def device() -> Device:
    return _make_device()


@pytest.fixture
def device_repo(device: Device) -> FakeDeviceRepository:
    return FakeDeviceRepository([device])


@pytest.fixture
def event_repo() -> FakeAccessEventRepository:
    return FakeAccessEventRepository()


@pytest.fixture
def user_repo() -> FakeUserRepository:
    return FakeUserRepository([])


@pytest.fixture
def policy_repo() -> FakeAccessPolicyRepository:
    return FakeAccessPolicyRepository([])


@pytest.fixture
def redis_client() -> FakeRedis:
    return FakeRedis()


def _client(
    *,
    device_repo: FakeDeviceRepository,
    event_repo: FakeAccessEventRepository,
    user_repo: FakeUserRepository,
    policy_repo: FakeAccessPolicyRepository,
    redis_client: FakeRedis,
    staff_role: StaffRole | None = None,
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_device_repository_auth] = lambda: device_repo
    app.dependency_overrides[get_device_repository_devices] = lambda: device_repo
    app.dependency_overrides[get_device_audit_log_repository] = FakeDeviceAuditLogRepository
    app.dependency_overrides[get_access_event_repository] = lambda: event_repo
    app.dependency_overrides[get_user_repository] = lambda: user_repo
    app.dependency_overrides[get_access_policy_repository] = lambda: policy_repo
    app.dependency_overrides[get_redis_client] = lambda: redis_client
    if staff_role is not None:
        app.dependency_overrides[get_current_staff] = lambda: CurrentStaff(
            id=uuid.uuid4(), email=f"{staff_role.value.lower()}@example.com", role=staff_role
        )
    return TestClient(app, raise_server_exceptions=False)


def _register_device_and_get_credential(client: TestClient, admin_role_client: TestClient) -> str:
    """Uses the real /devices registration flow so the returned credential
    is a real `<credential_id>.<secret>` token, exercised through the
    genuine `device_service`/Argon2 code path (see module docstring)."""
    response = admin_role_client.post(
        "/api/v1/devices", json={"name": "Ingest Door", "door_group": "main-entrance"}
    )
    assert response.status_code == 201
    return response.json()


# --- POST /access-events (device-authenticated ingest) ---------------------


def test_ingest_requires_device_authentication(
    device_repo, event_repo, user_repo, policy_repo, redis_client
) -> None:
    client = _client(
        device_repo=device_repo,
        event_repo=event_repo,
        user_repo=user_repo,
        policy_repo=policy_repo,
        redis_client=redis_client,
    )
    response = client.post("/api/v1/access-events", json={"decision": "DENIED"})
    assert response.status_code == 401


def test_ingest_rejects_invalid_device_credential(
    device_repo, event_repo, user_repo, policy_repo, redis_client
) -> None:
    client = _client(
        device_repo=device_repo,
        event_repo=event_repo,
        user_repo=user_repo,
        policy_repo=policy_repo,
        redis_client=redis_client,
    )
    response = client.post(
        "/api/v1/access-events",
        json={"decision": "DENIED"},
        headers={"Authorization": "Bearer bogus.credential"},
    )
    assert response.status_code == 401


def _issue_device_credential(device_repo: FakeDeviceRepository, device: Device) -> str:
    """Issue a real credential for `device` directly through device_service
    (avoids needing a separate ADMIN staff client just to register)."""
    from app.services import device_service

    issued = device_service.register_device(
        device_repo,
        FakeDeviceAuditLogRepository(),
        name=device.name,
        door_group=device.door_group,
        actor="test-setup",
    )
    # register_device() creates a NEW device row; swap our fixture device's
    # identity to match so `device` fixture and the credential agree.
    device.id = issued.device.id
    device.auth_credential_ref = issued.device.auth_credential_ref
    device.credential_hash = issued.device.credential_hash
    return issued.plaintext_token


@pytest.fixture
def device_credential(device_repo: FakeDeviceRepository, device: Device) -> str:
    return _issue_device_credential(device_repo, device)


def _auth_headers(credential: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {credential}"}


def test_ingest_denied_decision_never_issues_door_command(
    device_repo, event_repo, user_repo, policy_repo, redis_client, device, device_credential
) -> None:
    client = _client(
        device_repo=device_repo,
        event_repo=event_repo,
        user_repo=user_repo,
        policy_repo=policy_repo,
        redis_client=redis_client,
    )
    response = client.post(
        "/api/v1/access-events",
        json={"decision": "DENIED"},
        headers=_auth_headers(device_credential),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["decision"] == "DENIED"
    assert body["door_command_issued"] is False
    assert len(event_repo.events) == 1
    assert event_repo.events[0].device_id == device.id


def test_ingest_unknown_decision_never_issues_door_command(
    device_repo, event_repo, user_repo, policy_repo, redis_client, device_credential
) -> None:
    client = _client(
        device_repo=device_repo,
        event_repo=event_repo,
        user_repo=user_repo,
        policy_repo=policy_repo,
        redis_client=redis_client,
    )
    response = client.post(
        "/api/v1/access-events",
        json={"decision": "UNKNOWN"},
        headers=_auth_headers(device_credential),
    )
    assert response.status_code == 201
    assert response.json()["door_command_issued"] is False


def test_ingest_spoof_suspected_never_issues_door_command(
    device_repo, event_repo, user_repo, policy_repo, redis_client, device_credential
) -> None:
    client = _client(
        device_repo=device_repo,
        event_repo=event_repo,
        user_repo=user_repo,
        policy_repo=policy_repo,
        redis_client=redis_client,
    )
    response = client.post(
        "/api/v1/access-events",
        json={"decision": "SPOOF_SUSPECTED"},
        headers=_auth_headers(device_credential),
    )
    assert response.status_code == 201
    assert response.json()["door_command_issued"] is False


def test_ingest_granted_without_matched_user_never_issues_door_command(
    device_repo, event_repo, user_repo, policy_repo, redis_client, device_credential
) -> None:
    client = _client(
        device_repo=device_repo,
        event_repo=event_repo,
        user_repo=user_repo,
        policy_repo=policy_repo,
        redis_client=redis_client,
    )
    response = client.post(
        "/api/v1/access-events",
        json={"decision": "GRANTED"},
        headers=_auth_headers(device_credential),
    )
    assert response.status_code == 201
    assert response.json()["door_command_issued"] is False


def test_ingest_granted_cache_miss_is_fail_secure_deny(
    device_repo, event_repo, user_repo, policy_repo, redis_client, device_credential
) -> None:
    matched_user_id = uuid.uuid4()
    client = _client(
        device_repo=device_repo,
        event_repo=event_repo,
        user_repo=user_repo,
        policy_repo=policy_repo,
        redis_client=redis_client,
    )
    response = client.post(
        "/api/v1/access-events",
        json={"decision": "GRANTED", "matched_user_id": str(matched_user_id)},
        headers=_auth_headers(device_credential),
    )
    assert response.status_code == 201
    assert response.json()["door_command_issued"] is False


def test_ingest_granted_cache_hit_active_matching_policy_issues_door_command(
    device_repo, event_repo, user_repo, policy_repo, redis_client, device, device_credential
) -> None:
    matched_user_id = uuid.uuid4()
    redis_client.store[f"policy_snapshot:{matched_user_id}"] = _cache_snapshot_json(
        status=UserStatus.ACTIVE,
        policies=[_make_policy(user_id=matched_user_id, door_group=device.door_group)],
    )
    client = _client(
        device_repo=device_repo,
        event_repo=event_repo,
        user_repo=user_repo,
        policy_repo=policy_repo,
        redis_client=redis_client,
    )
    response = client.post(
        "/api/v1/access-events",
        json={"decision": "GRANTED", "matched_user_id": str(matched_user_id)},
        headers=_auth_headers(device_credential),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["door_command_issued"] is True
    assert event_repo.events[0].door_command_issued is True


def test_ingest_granted_cache_hit_suspended_user_denies(
    device_repo, event_repo, user_repo, policy_repo, redis_client, device, device_credential
) -> None:
    matched_user_id = uuid.uuid4()
    redis_client.store[f"policy_snapshot:{matched_user_id}"] = _cache_snapshot_json(
        status=UserStatus.SUSPENDED,
        policies=[_make_policy(user_id=matched_user_id, door_group=device.door_group)],
    )
    client = _client(
        device_repo=device_repo,
        event_repo=event_repo,
        user_repo=user_repo,
        policy_repo=policy_repo,
        redis_client=redis_client,
    )
    response = client.post(
        "/api/v1/access-events",
        json={"decision": "GRANTED", "matched_user_id": str(matched_user_id)},
        headers=_auth_headers(device_credential),
    )
    assert response.status_code == 201
    assert response.json()["door_command_issued"] is False


def test_ingest_granted_cache_hit_wrong_door_group_denies(
    device_repo, event_repo, user_repo, policy_repo, redis_client, device, device_credential
) -> None:
    matched_user_id = uuid.uuid4()
    redis_client.store[f"policy_snapshot:{matched_user_id}"] = _cache_snapshot_json(
        status=UserStatus.ACTIVE,
        policies=[_make_policy(user_id=matched_user_id, door_group="some-other-door-group")],
    )
    client = _client(
        device_repo=device_repo,
        event_repo=event_repo,
        user_repo=user_repo,
        policy_repo=policy_repo,
        redis_client=redis_client,
    )
    response = client.post(
        "/api/v1/access-events",
        json={"decision": "GRANTED", "matched_user_id": str(matched_user_id)},
        headers=_auth_headers(device_credential),
    )
    assert response.status_code == 201
    assert response.json()["door_command_issued"] is False


def test_ingest_granted_cache_hit_outside_valid_window_denies(
    device_repo, event_repo, user_repo, policy_repo, redis_client, device, device_credential
) -> None:
    matched_user_id = uuid.uuid4()
    now = datetime.now(UTC)
    redis_client.store[f"policy_snapshot:{matched_user_id}"] = _cache_snapshot_json(
        status=UserStatus.ACTIVE,
        policies=[
            _make_policy(
                user_id=matched_user_id,
                door_group=device.door_group,
                valid_from=now + timedelta(days=1),  # starts tomorrow
                valid_to=None,
            )
        ],
    )
    client = _client(
        device_repo=device_repo,
        event_repo=event_repo,
        user_repo=user_repo,
        policy_repo=policy_repo,
        redis_client=redis_client,
    )
    response = client.post(
        "/api/v1/access-events",
        json={"decision": "GRANTED", "matched_user_id": str(matched_user_id)},
        headers=_auth_headers(device_credential),
    )
    assert response.status_code == 201
    assert response.json()["door_command_issued"] is False


def test_ingest_device_id_always_comes_from_token_not_body(
    device_repo, event_repo, user_repo, policy_repo, redis_client, device, device_credential
) -> None:
    """The ingest schema has no `device_id` field at all — extra body fields
    are ignored — but this asserts the persisted event's device_id matches
    the authenticated device regardless."""
    other_device_id = str(uuid.uuid4())
    client = _client(
        device_repo=device_repo,
        event_repo=event_repo,
        user_repo=user_repo,
        policy_repo=policy_repo,
        redis_client=redis_client,
    )
    response = client.post(
        "/api/v1/access-events",
        json={"decision": "DENIED", "device_id": other_device_id},
        headers=_auth_headers(device_credential),
    )
    assert response.status_code == 201
    assert event_repo.events[0].device_id == device.id
    assert event_repo.events[0].device_id != uuid.UUID(other_device_id)


def test_ingest_disabled_device_is_403(
    device_repo, event_repo, user_repo, policy_repo, redis_client, device, device_credential
) -> None:
    device.status = DeviceStatus.DISABLED
    client = _client(
        device_repo=device_repo,
        event_repo=event_repo,
        user_repo=user_repo,
        policy_repo=policy_repo,
        redis_client=redis_client,
    )
    response = client.post(
        "/api/v1/access-events",
        json={"decision": "DENIED"},
        headers=_auth_headers(device_credential),
    )
    assert response.status_code == 403


# --- GET /access-events (staff read/monitoring) -----------------------------


def test_list_requires_authentication(
    device_repo, event_repo, user_repo, policy_repo, redis_client
) -> None:
    client = _client(
        device_repo=device_repo,
        event_repo=event_repo,
        user_repo=user_repo,
        policy_repo=policy_repo,
        redis_client=redis_client,
    )
    response = client.get("/api/v1/access-events")
    assert response.status_code == 401


def test_list_allowed_for_viewer(
    device_repo, event_repo, user_repo, policy_repo, redis_client, device
) -> None:
    event_repo.events.append(
        AccessEvent(
            id=uuid.uuid4(),
            occurred_at=datetime.now(UTC),
            device_id=device.id,
            decision=AccessDecision.DENIED,
            matched_user_id=None,
            similarity=None,
            liveness_score=None,
            model_version=None,
            latency_ms=None,
            frame_media_id=None,
            door_command_issued=False,
        )
    )
    client = _client(
        device_repo=device_repo,
        event_repo=event_repo,
        user_repo=user_repo,
        policy_repo=policy_repo,
        redis_client=redis_client,
        staff_role=StaffRole.VIEWER,
    )
    response = client.get("/api/v1/access-events")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["decision"] == "DENIED"


def test_list_filters_by_device_id_and_decision(
    device_repo, event_repo, user_repo, policy_repo, redis_client, device
) -> None:
    other_device_id = uuid.uuid4()
    now = datetime.now(UTC)
    event_repo.events.extend(
        [
            AccessEvent(
                id=uuid.uuid4(),
                occurred_at=now,
                device_id=device.id,
                decision=AccessDecision.GRANTED,
                matched_user_id=None,
                similarity=None,
                liveness_score=None,
                model_version=None,
                latency_ms=None,
                frame_media_id=None,
                door_command_issued=True,
            ),
            AccessEvent(
                id=uuid.uuid4(),
                occurred_at=now,
                device_id=other_device_id,
                decision=AccessDecision.DENIED,
                matched_user_id=None,
                similarity=None,
                liveness_score=None,
                model_version=None,
                latency_ms=None,
                frame_media_id=None,
                door_command_issued=False,
            ),
        ]
    )
    client = _client(
        device_repo=device_repo,
        event_repo=event_repo,
        user_repo=user_repo,
        policy_repo=policy_repo,
        redis_client=redis_client,
        staff_role=StaffRole.ADMIN,
    )
    response = client.get("/api/v1/access-events", params={"device_id": str(device.id)})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["device_id"] == str(device.id)

    response = client.get("/api/v1/access-events", params={"decision": "DENIED"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["decision"] == "DENIED"


def test_list_orders_newest_first(
    device_repo, event_repo, user_repo, policy_repo, redis_client, device
) -> None:
    now = datetime.now(UTC)
    older = AccessEvent(
        id=uuid.uuid4(),
        occurred_at=now - timedelta(minutes=5),
        device_id=device.id,
        decision=AccessDecision.DENIED,
        matched_user_id=None,
        similarity=None,
        liveness_score=None,
        model_version=None,
        latency_ms=None,
        frame_media_id=None,
        door_command_issued=False,
    )
    newer = AccessEvent(
        id=uuid.uuid4(),
        occurred_at=now,
        device_id=device.id,
        decision=AccessDecision.DENIED,
        matched_user_id=None,
        similarity=None,
        liveness_score=None,
        model_version=None,
        latency_ms=None,
        frame_media_id=None,
        door_command_issued=False,
    )
    event_repo.events.extend([older, newer])
    client = _client(
        device_repo=device_repo,
        event_repo=event_repo,
        user_repo=user_repo,
        policy_repo=policy_repo,
        redis_client=redis_client,
        staff_role=StaffRole.OPERATOR,
    )
    response = client.get("/api/v1/access-events")
    assert response.status_code == 200
    items = response.json()["items"]
    assert items[0]["id"] == str(newer.id)
    assert items[1]["id"] == str(older.id)
