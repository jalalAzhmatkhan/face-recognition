"""Integration tests for `/api/v1/access-policies/*` via FastAPI TestClient
(BE-10, FR-INF-05).

No real DB/Redis: every repository dependency is overridden with an
in-memory fake, `get_current_staff` is overridden directly (mirrors
test_devices_router.py/test_users_router.py), and `get_redis_client` is
overridden with a dict-backed `FakeRedis` so cache-refresh side effects
(app/services/policy_cache.py) are observable without a real Redis server.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.redis_client import get_redis_client
from app.dependencies.auth import CurrentStaff, get_current_staff
from app.main import create_app
from app.models.access_policy import AccessPolicy
from app.models.enums import StaffRole, UserStatus
from app.models.user import User
from app.routers.access_policies import (
    get_access_policy_repository,
    get_audit_log_repository,
    get_user_repository,
)


class FakeAccessPolicyRepository:
    def __init__(self, policies: list[AccessPolicy] | None = None) -> None:
        self._by_id: dict[uuid.UUID, AccessPolicy] = {p.id: p for p in (policies or [])}

    def get(self, policy_id: uuid.UUID) -> AccessPolicy | None:
        return self._by_id.get(policy_id)

    def list(
        self, *, user_id=None, door_group=None, limit: int = 100, offset: int = 0
    ) -> list[AccessPolicy]:
        items = list(self._by_id.values())
        if user_id is not None:
            items = [p for p in items if p.user_id == user_id]
        if door_group is not None:
            items = [p for p in items if p.door_group == door_group]
        items.sort(key=lambda p: p.door_group)
        return items[offset : offset + limit]

    def count(self, *, user_id=None, door_group=None) -> int:
        return len(self.list(user_id=user_id, door_group=door_group, limit=10**9, offset=0))

    def list_for_user(self, user_id: uuid.UUID) -> list[AccessPolicy]:
        return [p for p in self._by_id.values() if p.user_id == user_id]

    def create(self, policy: AccessPolicy) -> AccessPolicy:
        policy.id = policy.id or uuid.uuid4()
        self._by_id[policy.id] = policy
        return policy

    def update(self, policy: AccessPolicy) -> AccessPolicy:
        self._by_id[policy.id] = policy
        return policy

    def delete(self, policy: AccessPolicy) -> None:
        self._by_id.pop(policy.id, None)


class FakeUserRepository:
    def __init__(self, users: list[User] | None = None) -> None:
        self._by_id: dict[uuid.UUID, User] = {u.id: u for u in (users or [])}

    def get(self, user_id: uuid.UUID) -> User | None:
        return self._by_id.get(user_id)


class FakeAuditLogRepository:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def record(self, *, actor: str, action: str, entity: str, payload=None):
        entry = {"actor": actor, "action": action, "entity": entity, "payload": payload}
        self.entries.append(entry)
        return entry


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


def _make_policy(
    *, user_id=None, group_id=None, door_group="main-entrance", allowed=True
) -> AccessPolicy:
    return AccessPolicy(
        id=uuid.uuid4(),
        user_id=user_id,
        group_id=group_id,
        door_group=door_group,
        allowed=allowed,
        valid_from=None,
        valid_to=None,
    )


def _make_user(status: UserStatus = UserStatus.ACTIVE) -> User:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    return User(
        id=uuid.uuid4(),
        external_ref=f"EMP-{uuid.uuid4().hex[:6]}",
        full_name="Test Person",
        status=status,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def existing_user() -> User:
    return _make_user()


@pytest.fixture
def policy_repo(existing_user: User) -> FakeAccessPolicyRepository:
    return FakeAccessPolicyRepository(
        [
            _make_policy(user_id=existing_user.id, door_group="main-entrance"),
            _make_policy(door_group="warehouse", allowed=False),
        ]
    )


@pytest.fixture
def user_repo(existing_user: User) -> FakeUserRepository:
    return FakeUserRepository([existing_user])


@pytest.fixture
def audit_repo() -> FakeAuditLogRepository:
    return FakeAuditLogRepository()


@pytest.fixture
def redis_client() -> FakeRedis:
    return FakeRedis()


def _client(
    policy_repo: FakeAccessPolicyRepository,
    user_repo: FakeUserRepository,
    audit_repo: FakeAuditLogRepository,
    redis_client: FakeRedis,
    role: StaffRole,
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_access_policy_repository] = lambda: policy_repo
    app.dependency_overrides[get_user_repository] = lambda: user_repo
    app.dependency_overrides[get_audit_log_repository] = lambda: audit_repo
    app.dependency_overrides[get_redis_client] = lambda: redis_client
    app.dependency_overrides[get_current_staff] = lambda: CurrentStaff(
        id=uuid.uuid4(), email=f"{role.value.lower()}@example.com", role=role
    )
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def admin_client(policy_repo, user_repo, audit_repo, redis_client) -> TestClient:
    return _client(policy_repo, user_repo, audit_repo, redis_client, StaffRole.ADMIN)


@pytest.fixture
def operator_client(policy_repo, user_repo, audit_repo, redis_client) -> TestClient:
    return _client(policy_repo, user_repo, audit_repo, redis_client, StaffRole.OPERATOR)


@pytest.fixture
def viewer_client(policy_repo, user_repo, audit_repo, redis_client) -> TestClient:
    return _client(policy_repo, user_repo, audit_repo, redis_client, StaffRole.VIEWER)


# --- GET /access-policies (list) -------------------------------------------


def test_list_allowed_for_admin(admin_client: TestClient) -> None:
    response = admin_client.get("/api/v1/access-policies")
    assert response.status_code == 200
    assert response.json()["total"] == 2


def test_list_allowed_for_operator(operator_client: TestClient) -> None:
    response = operator_client.get("/api/v1/access-policies")
    assert response.status_code == 200


def test_list_denied_for_viewer(viewer_client: TestClient) -> None:
    response = viewer_client.get("/api/v1/access-policies")
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")


def test_list_requires_authentication() -> None:
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/v1/access-policies")
    assert response.status_code == 401


def test_list_filters_by_door_group(admin_client: TestClient) -> None:
    response = admin_client.get("/api/v1/access-policies", params={"door_group": "warehouse"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["door_group"] == "warehouse"


def test_list_filters_by_user_id(admin_client: TestClient, existing_user: User) -> None:
    response = admin_client.get(
        "/api/v1/access-policies", params={"user_id": str(existing_user.id)}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["user_id"] == str(existing_user.id)


# --- POST /access-policies (create) ----------------------------------------


def test_create_denied_for_operator(operator_client: TestClient, existing_user: User) -> None:
    response = operator_client.post(
        "/api/v1/access-policies",
        json={"user_id": str(existing_user.id), "door_group": "roof"},
    )
    assert response.status_code == 403


def test_create_denied_for_viewer(viewer_client: TestClient, existing_user: User) -> None:
    response = viewer_client.post(
        "/api/v1/access-policies",
        json={"user_id": str(existing_user.id), "door_group": "roof"},
    )
    assert response.status_code == 403


def test_create_rejects_neither_user_nor_group(admin_client: TestClient) -> None:
    response = admin_client.post("/api/v1/access-policies", json={"door_group": "roof"})
    assert response.status_code == 422


def test_create_succeeds_with_user_id(
    admin_client: TestClient, existing_user: User, audit_repo: FakeAuditLogRepository
) -> None:
    response = admin_client.post(
        "/api/v1/access-policies",
        json={"user_id": str(existing_user.id), "door_group": "roof", "allowed": True},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["door_group"] == "roof"
    assert body["user_id"] == str(existing_user.id)
    assert any(e["action"] == "access_policy.create" for e in audit_repo.entries)


def test_create_with_user_id_refreshes_cache(
    admin_client: TestClient, existing_user: User, redis_client: FakeRedis
) -> None:
    response = admin_client.post(
        "/api/v1/access-policies",
        json={"user_id": str(existing_user.id), "door_group": "roof", "allowed": True},
    )
    assert response.status_code == 201
    assert f"policy_snapshot:{existing_user.id}" in redis_client.store


def test_create_with_only_group_id_succeeds_without_cache_refresh(
    admin_client: TestClient, redis_client: FakeRedis
) -> None:
    group_id = uuid.uuid4()
    response = admin_client.post(
        "/api/v1/access-policies",
        json={"group_id": str(group_id), "door_group": "roof", "allowed": True},
    )
    assert response.status_code == 201
    # No user_id-scoped cache entry should ever be written for a purely
    # group-scoped policy (v1 has no group-membership resolution — see
    # app/services/policy_cache.py).
    assert redis_client.store == {}


# --- PATCH /access-policies/{id} --------------------------------------------


def test_update_allowed_succeeds_for_admin(
    admin_client: TestClient, policy_repo: FakeAccessPolicyRepository, existing_user: User
) -> None:
    policy_id = next(
        p.id for p in policy_repo._by_id.values() if p.user_id == existing_user.id
    )
    response = admin_client.patch(
        f"/api/v1/access-policies/{policy_id}", json={"allowed": False}
    )
    assert response.status_code == 200
    assert response.json()["allowed"] is False


def test_update_refreshes_cache_for_affected_user(
    admin_client: TestClient,
    policy_repo: FakeAccessPolicyRepository,
    existing_user: User,
    redis_client: FakeRedis,
) -> None:
    policy_id = next(
        p.id for p in policy_repo._by_id.values() if p.user_id == existing_user.id
    )
    response = admin_client.patch(
        f"/api/v1/access-policies/{policy_id}", json={"allowed": False}
    )
    assert response.status_code == 200
    assert f"policy_snapshot:{existing_user.id}" in redis_client.store


def test_update_denied_for_operator(
    operator_client: TestClient, policy_repo: FakeAccessPolicyRepository
) -> None:
    policy_id = next(iter(policy_repo._by_id))
    response = operator_client.patch(
        f"/api/v1/access-policies/{policy_id}", json={"allowed": False}
    )
    assert response.status_code == 403


def test_update_returns_404_for_unknown_id(admin_client: TestClient) -> None:
    response = admin_client.patch(
        f"/api/v1/access-policies/{uuid.uuid4()}", json={"allowed": False}
    )
    assert response.status_code == 404


# --- DELETE /access-policies/{id} -------------------------------------------


def test_delete_removes_row_for_admin(
    admin_client: TestClient, policy_repo: FakeAccessPolicyRepository
) -> None:
    policy_id = next(iter(policy_repo._by_id))
    response = admin_client.delete(f"/api/v1/access-policies/{policy_id}")
    assert response.status_code == 204
    assert policy_repo.get(policy_id) is None


def test_delete_refreshes_cache_for_affected_user(
    admin_client: TestClient,
    policy_repo: FakeAccessPolicyRepository,
    existing_user: User,
    redis_client: FakeRedis,
) -> None:
    policy_id = next(
        p.id for p in policy_repo._by_id.values() if p.user_id == existing_user.id
    )
    response = admin_client.delete(f"/api/v1/access-policies/{policy_id}")
    assert response.status_code == 204
    # After the only policy for this user is deleted, the refreshed snapshot
    # has an empty policies list (still cached — a valid, empty snapshot).
    assert f"policy_snapshot:{existing_user.id}" in redis_client.store


def test_delete_denied_for_operator(
    operator_client: TestClient, policy_repo: FakeAccessPolicyRepository
) -> None:
    policy_id = next(iter(policy_repo._by_id))
    response = operator_client.delete(f"/api/v1/access-policies/{policy_id}")
    assert response.status_code == 403


def test_delete_returns_404_for_unknown_id(admin_client: TestClient) -> None:
    response = admin_client.delete(f"/api/v1/access-policies/{uuid.uuid4()}")
    assert response.status_code == 404
