"""BE-10 integration: a user-status change via `/api/v1/users/*` must
proactively refresh that user's policy-snapshot cache (TSD §2.2, FR-INF-05)
rather than waiting for the <=30s TTL to expire passively.

Kept in its own file (rather than extending test_users_router.py) since it
overrides two extra dependencies (`get_access_policy_repository`,
`get_redis_client`) that BE-04's own tests never needed and deliberately
leaves unmocked — this file tests exactly the BE-10 addition end to end,
including the "best-effort, never breaks the request" failure mode.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.core.redis_client import get_redis_client
from app.dependencies.auth import CurrentStaff, get_current_staff
from app.main import create_app
from app.models.access_policy import AccessPolicy
from app.models.enums import StaffRole, UserStatus
from app.models.user import User
from app.routers.users import (
    get_access_policy_repository,
    get_audit_log_repository,
    get_user_repository,
)


class FakeUserRepository:
    def __init__(self, users: list[User] | None = None) -> None:
        self._by_id: dict[uuid.UUID, User] = {u.id: u for u in (users or [])}

    def get(self, user_id: uuid.UUID) -> User | None:
        return self._by_id.get(user_id)

    def get_by_external_ref(self, external_ref: str) -> User | None:
        for u in self._by_id.values():
            if u.external_ref == external_ref:
                return u
        return None

    def list(self, *, status=None, limit: int = 100, offset: int = 0) -> list[User]:
        items = list(self._by_id.values())
        if status is not None:
            items = [u for u in items if u.status == status]
        return items[offset : offset + limit]

    def count(self, *, status=None) -> int:
        return len(self.list(status=status, limit=10**9, offset=0))

    def create(self, user: User) -> User:
        user.id = user.id or uuid.uuid4()
        self._by_id[user.id] = user
        return user

    def update(self, user: User) -> User:
        self._by_id[user.id] = user
        return user


class FakeAccessPolicyRepository:
    def __init__(self, policies: list[AccessPolicy] | None = None) -> None:
        self._policies = list(policies or [])

    def list_for_user(self, user_id: uuid.UUID) -> list[AccessPolicy]:
        return [p for p in self._policies if p.user_id == user_id]


class FakeAuditLogRepository:
    def record(self, **_kwargs):
        return None


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.set_calls: list[str] = []

    def get(self, name: str):
        return self.store.get(name)

    def set(self, name: str, value: str, ex=None):
        self.set_calls.append(name)
        self.store[name] = value
        return True

    def delete(self, name: str):
        return 1 if self.store.pop(name, None) is not None else 0


class FailingRedis:
    def get(self, name: str):
        raise ConnectionError("simulated Redis outage")

    def set(self, name: str, value: str, ex=None):
        raise ConnectionError("simulated Redis outage")

    def delete(self, name: str):
        raise ConnectionError("simulated Redis outage")


def _make_user(status: UserStatus = UserStatus.ACTIVE) -> User:
    now = datetime.now(UTC)
    return User(
        id=uuid.uuid4(),
        external_ref=f"EMP-{uuid.uuid4().hex[:6]}",
        full_name="Cache Refresh Target",
        status=status,
        created_at=now,
        updated_at=now,
    )


def _client(user_repo, policy_repo, redis_client) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_user_repository] = lambda: user_repo
    app.dependency_overrides[get_audit_log_repository] = FakeAuditLogRepository
    app.dependency_overrides[get_access_policy_repository] = lambda: policy_repo
    app.dependency_overrides[get_redis_client] = lambda: redis_client
    app.dependency_overrides[get_current_staff] = lambda: CurrentStaff(
        id=uuid.uuid4(), email="admin@example.com", role=StaffRole.ADMIN
    )
    return TestClient(app, raise_server_exceptions=False)


def test_status_change_via_patch_refreshes_policy_cache() -> None:
    user = _make_user(UserStatus.ACTIVE)
    user_repo = FakeUserRepository([user])
    policy_repo = FakeAccessPolicyRepository(
        [
            AccessPolicy(
                id=uuid.uuid4(),
                user_id=user.id,
                group_id=None,
                door_group="main-entrance",
                allowed=True,
                valid_from=None,
                valid_to=None,
            )
        ]
    )
    redis_client = FakeRedis()
    client = _client(user_repo, policy_repo, redis_client)

    response = client.patch(f"/api/v1/users/{user.id}", json={"status": "SUSPENDED"})

    assert response.status_code == 200
    key = f"policy_snapshot:{user.id}"
    assert key in redis_client.store
    import json

    cached = json.loads(redis_client.store[key])
    assert cached["status"] == "SUSPENDED"  # reflects the NEW status, not stale ACTIVE


def test_full_name_only_update_does_not_touch_cache() -> None:
    """Only a status change should trigger a refresh — an unrelated field
    edit shouldn't pay the (small) extra DB+Redis round trip."""
    user = _make_user(UserStatus.ACTIVE)
    user_repo = FakeUserRepository([user])
    policy_repo = FakeAccessPolicyRepository([])
    redis_client = FakeRedis()
    client = _client(user_repo, policy_repo, redis_client)

    response = client.patch(f"/api/v1/users/{user.id}", json={"full_name": "Renamed"})

    assert response.status_code == 200
    assert redis_client.set_calls == []


def test_delete_user_offboard_refreshes_policy_cache() -> None:
    user = _make_user(UserStatus.ACTIVE)
    user_repo = FakeUserRepository([user])
    policy_repo = FakeAccessPolicyRepository([])
    redis_client = FakeRedis()
    client = _client(user_repo, policy_repo, redis_client)

    response = client.delete(f"/api/v1/users/{user.id}")

    assert response.status_code == 200
    key = f"policy_snapshot:{user.id}"
    assert key in redis_client.store
    import json

    cached = json.loads(redis_client.store[key])
    assert cached["status"] == "OFFBOARDED"


def test_status_change_survives_redis_outage_without_500(caplog: pytest.LogCaptureFixture) -> None:
    """A Redis outage during the best-effort refresh must not turn a
    legitimate status-change request into a 500 (FR-INF-05's fail-secure
    posture is about the DOOR decision, not about breaking admin writes)."""
    user = _make_user(UserStatus.ACTIVE)
    user_repo = FakeUserRepository([user])
    policy_repo = FakeAccessPolicyRepository([])
    redis_client = FailingRedis()
    client = _client(user_repo, policy_repo, redis_client)

    response = client.patch(f"/api/v1/users/{user.id}", json={"status": "SUSPENDED"})

    assert response.status_code == 200
    assert response.json()["status"] == "SUSPENDED"
