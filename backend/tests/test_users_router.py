"""Integration tests for `/api/v1/users/*` via FastAPI TestClient (BE-04).

No real DB: `get_user_repository`/`get_audit_log_repository` are overridden
with in-memory fakes, and `get_current_staff` is overridden directly to
avoid re-deriving the whole JWT login flow for every RBAC scenario (mirrors
the fake-repository pattern established in test_auth_router.py).
"""

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.dependencies.auth import CurrentStaff, get_current_staff
from app.main import create_app
from app.models.enums import StaffRole, UserStatus
from app.models.user import User
from app.routers.users import get_audit_log_repository, get_user_repository


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

    def list(
        self, *, status: UserStatus | None = None, limit: int = 100, offset: int = 0
    ) -> list[User]:
        items = list(self._by_id.values())
        if status is not None:
            items = [u for u in items if u.status == status]
        items.sort(key=lambda u: u.created_at)
        return items[offset : offset + limit]

    def count(self, *, status: UserStatus | None = None) -> int:
        items = list(self._by_id.values())
        if status is not None:
            items = [u for u in items if u.status == status]
        return len(items)

    def create(self, user: User) -> User:
        now = datetime.now(UTC)
        user.id = user.id or uuid.uuid4()
        user.created_at = now
        user.updated_at = now
        self._by_id[user.id] = user
        return user

    def update(self, user: User) -> User:
        user.updated_at = datetime.now(UTC)
        self._by_id[user.id] = user
        return user


class FakeAuditLogRepository:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def record(self, *, actor: str, action: str, entity: str, payload=None):
        entry = {"actor": actor, "action": action, "entity": entity, "payload": payload}
        self.entries.append(entry)
        return entry


def _make_user(external_ref: str, full_name: str, status: UserStatus = UserStatus.ACTIVE) -> User:
    now = datetime.now(UTC)
    return User(
        id=uuid.uuid4(),
        external_ref=external_ref,
        full_name=full_name,
        status=status,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def user_repo() -> FakeUserRepository:
    return FakeUserRepository(
        [
            _make_user("EMP-001", "Alice Active"),
            _make_user("EMP-002", "Bob Suspended", UserStatus.SUSPENDED),
        ]
    )


@pytest.fixture
def audit_repo() -> FakeAuditLogRepository:
    return FakeAuditLogRepository()


def _client(
    user_repo: FakeUserRepository, audit_repo: FakeAuditLogRepository, role: StaffRole
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_user_repository] = lambda: user_repo
    app.dependency_overrides[get_audit_log_repository] = lambda: audit_repo
    app.dependency_overrides[get_current_staff] = lambda: CurrentStaff(
        id=uuid.uuid4(), email=f"{role.value.lower()}@example.com", role=role
    )
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def admin_client(user_repo, audit_repo) -> TestClient:
    return _client(user_repo, audit_repo, StaffRole.ADMIN)


@pytest.fixture
def operator_client(user_repo, audit_repo) -> TestClient:
    return _client(user_repo, audit_repo, StaffRole.OPERATOR)


@pytest.fixture
def viewer_client(user_repo, audit_repo) -> TestClient:
    return _client(user_repo, audit_repo, StaffRole.VIEWER)


# --- GET /users (list) -------------------------------------------------


def test_list_users_returns_all(viewer_client: TestClient) -> None:
    response = viewer_client.get("/api/v1/users")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2
    assert body["limit"] == 50
    assert body["offset"] == 0


def test_list_users_filters_by_status(viewer_client: TestClient) -> None:
    response = viewer_client.get("/api/v1/users", params={"status": "SUSPENDED"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["full_name"] == "Bob Suspended"


def test_list_users_pagination(viewer_client: TestClient) -> None:
    response = viewer_client.get("/api/v1/users", params={"limit": 1, "offset": 1})
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    assert body["total"] == 2


def test_list_users_requires_authentication() -> None:
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/v1/users")
    assert response.status_code == 401


# --- POST /users (create) ----------------------------------------------


def test_create_user_succeeds_for_admin(admin_client: TestClient, audit_repo) -> None:
    response = admin_client.post(
        "/api/v1/users", json={"external_ref": "EMP-999", "full_name": "New Person"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["external_ref"] == "EMP-999"
    assert body["status"] == "ACTIVE"
    assert any(e["action"] == "user.create" for e in audit_repo.entries)


def test_create_user_succeeds_for_operator(operator_client: TestClient) -> None:
    response = operator_client.post(
        "/api/v1/users", json={"external_ref": "EMP-998", "full_name": "New Person 2"}
    )
    assert response.status_code == 201


def test_create_user_denied_for_viewer(viewer_client: TestClient) -> None:
    response = viewer_client.post(
        "/api/v1/users", json={"external_ref": "EMP-997", "full_name": "Nope"}
    )
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")


def test_create_user_rejects_duplicate_external_ref(admin_client: TestClient) -> None:
    response = admin_client.post(
        "/api/v1/users", json={"external_ref": "EMP-001", "full_name": "Duplicate"}
    )
    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")


def test_create_user_rejects_blank_full_name(admin_client: TestClient) -> None:
    response = admin_client.post(
        "/api/v1/users", json={"external_ref": "EMP-996", "full_name": ""}
    )
    assert response.status_code == 422


def test_create_user_rejects_missing_external_ref(admin_client: TestClient) -> None:
    response = admin_client.post("/api/v1/users", json={"full_name": "No Ref"})
    assert response.status_code == 422


# --- GET /users/{id} -----------------------------------------------------


def test_get_user_returns_detail(viewer_client: TestClient, user_repo: FakeUserRepository) -> None:
    existing_id = next(iter(user_repo._by_id))
    response = viewer_client.get(f"/api/v1/users/{existing_id}")
    assert response.status_code == 200
    assert response.json()["id"] == str(existing_id)


def test_get_user_returns_404_for_unknown_id(viewer_client: TestClient) -> None:
    response = viewer_client.get(f"/api/v1/users/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


# --- PATCH /users/{id} ----------------------------------------------------


def test_update_user_full_name_succeeds_for_admin(
    admin_client: TestClient, user_repo: FakeUserRepository
) -> None:
    existing_id = next(iter(user_repo._by_id))
    response = admin_client.patch(
        f"/api/v1/users/{existing_id}", json={"full_name": "Renamed"}
    )
    assert response.status_code == 200
    assert response.json()["full_name"] == "Renamed"


def test_update_user_status_to_offboarded_writes_audit_entry(
    admin_client: TestClient, user_repo: FakeUserRepository, audit_repo
) -> None:
    existing_id = next(iter(user_repo._by_id))
    response = admin_client.patch(
        f"/api/v1/users/{existing_id}", json={"status": "OFFBOARDED"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "OFFBOARDED"
    status_changes = [e for e in audit_repo.entries if e["action"] == "user.status_change"]
    assert len(status_changes) == 1
    assert status_changes[0]["payload"] == {"from": "ACTIVE", "to": "OFFBOARDED"}


def test_update_user_status_allowed_for_operator(
    operator_client: TestClient, user_repo: FakeUserRepository
) -> None:
    existing_id = next(iter(user_repo._by_id))
    response = operator_client.patch(
        f"/api/v1/users/{existing_id}", json={"status": "OFFBOARDED"}
    )
    assert response.status_code == 200


def test_update_user_denied_for_viewer(
    viewer_client: TestClient, user_repo: FakeUserRepository
) -> None:
    existing_id = next(iter(user_repo._by_id))
    response = viewer_client.patch(f"/api/v1/users/{existing_id}", json={"full_name": "Nope"})
    assert response.status_code == 403


def test_update_user_returns_404_for_unknown_id(admin_client: TestClient) -> None:
    response = admin_client.patch(
        f"/api/v1/users/{uuid.uuid4()}", json={"full_name": "Ghost"}
    )
    assert response.status_code == 404


def test_update_user_rejects_duplicate_external_ref(
    admin_client: TestClient, user_repo: FakeUserRepository
) -> None:
    ids = list(user_repo._by_id.keys())
    bob_id = next(uid for uid, u in user_repo._by_id.items() if u.external_ref == "EMP-002")
    response = admin_client.patch(
        f"/api/v1/users/{bob_id}", json={"external_ref": "EMP-001"}
    )
    assert response.status_code == 409
    assert bob_id in ids


def test_update_user_rejects_invalid_status_enum(
    admin_client: TestClient, user_repo: FakeUserRepository
) -> None:
    existing_id = next(iter(user_repo._by_id))
    response = admin_client.patch(
        f"/api/v1/users/{existing_id}", json={"status": "NOT_A_STATUS"}
    )
    assert response.status_code == 422


# --- DELETE /users/{id} (alias for OFFBOARDED) ----------------------------


def test_delete_user_offboards_instead_of_hard_delete(
    admin_client: TestClient, user_repo: FakeUserRepository, audit_repo
) -> None:
    existing_id = next(iter(user_repo._by_id))
    response = admin_client.delete(f"/api/v1/users/{existing_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "OFFBOARDED"
    # Row still exists in the repository — not actually removed.
    assert user_repo.get(existing_id) is not None
    assert any(e["action"] == "user.status_change" for e in audit_repo.entries)


def test_delete_user_denied_for_viewer(
    viewer_client: TestClient, user_repo: FakeUserRepository
) -> None:
    existing_id = next(iter(user_repo._by_id))
    response = viewer_client.delete(f"/api/v1/users/{existing_id}")
    assert response.status_code == 403


def test_delete_user_returns_404_for_unknown_id(admin_client: TestClient) -> None:
    response = admin_client.delete(f"/api/v1/users/{uuid.uuid4()}")
    assert response.status_code == 404
