"""Integration tests for `/api/v1/auth/*` via FastAPI TestClient (BE-03).

No real DB: `get_staff_account_repository` is overridden with an in-memory
fake, so `create_app()` never touches `DATABASE_URL`/a live Postgres.
"""

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.dependencies.auth import (
    get_password_reset_token_repository,
    get_staff_account_repository,
)
from app.main import create_app
from app.models.enums import StaffRole
from app.models.password_reset_token import PasswordResetToken
from app.models.staff_account import StaffAccount
from app.services import auth_service


class FakeStaffAccountRepository:
    def __init__(self, accounts: list[StaffAccount]) -> None:
        self._by_id = {a.id: a for a in accounts}
        self._by_email = {a.email: a for a in accounts}

    def get(self, staff_id: uuid.UUID) -> StaffAccount | None:
        return self._by_id.get(staff_id)

    def get_by_email(self, email: str) -> StaffAccount | None:
        return self._by_email.get(email)

    def exists_by_role(self, role: StaffRole) -> bool:
        return any(a.role == role for a in self._by_id.values())

    def create(self, account: StaffAccount) -> StaffAccount:
        # Mimics the ID being assigned on INSERT by a real session/DB flush
        # (`UUIDPKMixin.id`'s `default=uuid.uuid4` is a client-side default
        # SQLAlchemy applies at flush time, not at object construction) --
        # this fake never touches a real session, so it must assign one
        # itself.
        if account.id is None:
            account.id = uuid.uuid4()
        self._by_id[account.id] = account
        self._by_email[account.email] = account
        return account

    def update_password_hash(self, account: StaffAccount, password_hash: str) -> None:
        account.password_hash = password_hash


class FakePasswordResetTokenRepository:
    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, PasswordResetToken] = {}

    def get(self, token_id: uuid.UUID) -> PasswordResetToken | None:
        return self._by_id.get(token_id)

    def create(self, token: PasswordResetToken) -> PasswordResetToken:
        self._by_id[token.id] = token
        return token

    def mark_used(self, token: PasswordResetToken) -> None:
        token.used_at = datetime.now(UTC)


ADMIN_PASSWORD = "S0meStrongPass!"
VIEWER_PASSWORD = "AnotherPass!23"


@pytest.fixture
def accounts() -> dict[str, StaffAccount]:
    admin = StaffAccount(
        id=uuid.uuid4(),
        email="admin@example.com",
        role=StaffRole.ADMIN,
        password_hash=hash_password(ADMIN_PASSWORD),
    )
    viewer = StaffAccount(
        id=uuid.uuid4(),
        email="viewer@example.com",
        role=StaffRole.VIEWER,
        password_hash=hash_password(VIEWER_PASSWORD),
    )
    return {"admin": admin, "viewer": viewer}


@pytest.fixture
def token_repo() -> FakePasswordResetTokenRepository:
    return FakePasswordResetTokenRepository()


@pytest.fixture
def client(
    accounts: dict[str, StaffAccount], token_repo: FakePasswordResetTokenRepository
) -> TestClient:
    app = create_app()
    fake_repo = FakeStaffAccountRepository(list(accounts.values()))
    app.dependency_overrides[get_staff_account_repository] = lambda: fake_repo
    app.dependency_overrides[get_password_reset_token_repository] = lambda: token_repo
    return TestClient(app, raise_server_exceptions=False)


def test_login_succeeds_with_correct_credentials(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["expires_in"] > 0


def test_login_fails_with_wrong_password(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": "wrong"}
    )
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["status"] == 401


def test_login_fails_with_nonexistent_email_same_as_wrong_password(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever"}
    )
    assert response.status_code == 401
    wrong_pw_response = client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": "wrong"}
    )
    # Identical body — no leak of which part (email/password) was wrong.
    assert response.json()["detail"] == wrong_pw_response.json()["detail"]


def test_refresh_returns_new_access_token(client: TestClient) -> None:
    login_response = client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": ADMIN_PASSWORD}
    )
    refresh_token = login_response.json()["refresh_token"]

    response = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 200
    assert response.json()["access_token"]


def test_refresh_rejects_invalid_token(client: TestClient) -> None:
    response = client.post("/api/v1/auth/refresh", json={"refresh_token": "not-a-jwt"})
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")


def test_refresh_rejects_access_token_used_as_refresh_token(client: TestClient) -> None:
    login_response = client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": ADMIN_PASSWORD}
    )
    access_token = login_response.json()["access_token"]

    response = client.post("/api/v1/auth/refresh", json={"refresh_token": access_token})
    assert response.status_code == 401


def test_me_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_me_returns_identity_for_valid_token(client: TestClient) -> None:
    login_response = client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": ADMIN_PASSWORD}
    )
    access_token = login_response.json()["access_token"]

    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "admin@example.com"
    assert body["role"] == "ADMIN"


def test_admin_only_endpoint_denies_viewer_role(client: TestClient) -> None:
    login_response = client.post(
        "/api/v1/auth/login", json={"email": "viewer@example.com", "password": VIEWER_PASSWORD}
    )
    access_token = login_response.json()["access_token"]

    response = client.get(
        "/api/v1/auth/admin-only-example", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")


def test_admin_only_endpoint_allows_admin_role(client: TestClient) -> None:
    login_response = client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": ADMIN_PASSWORD}
    )
    access_token = login_response.json()["access_token"]

    response = client.get(
        "/api/v1/auth/admin-only-example", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert response.status_code == 200


def test_admin_only_endpoint_denies_missing_token_with_401_not_403(client: TestClient) -> None:
    """Missing/invalid credentials must surface as 401 (unauthenticated), not
    403 (unauthorized) — require_role always resolves get_current_staff first."""
    response = client.get("/api/v1/auth/admin-only-example")
    assert response.status_code == 401


def _empty_client() -> tuple[TestClient, FakePasswordResetTokenRepository]:
    app = create_app()
    fake_repo = FakeStaffAccountRepository([])
    fake_token_repo = FakePasswordResetTokenRepository()
    app.dependency_overrides[get_staff_account_repository] = lambda: fake_repo
    app.dependency_overrides[get_password_reset_token_repository] = lambda: fake_token_repo
    return TestClient(app, raise_server_exceptions=False), fake_token_repo


def test_setup_status_reports_needs_setup_true_with_no_admin() -> None:
    # `accounts` fixture only seeds an ADMIN + a VIEWER, so this branch is
    # exercised via an empty-repo client instead.
    empty_client, _ = _empty_client()

    response = empty_client.get("/api/v1/auth/setup-status")
    assert response.status_code == 200
    assert response.json() == {"needs_setup": True}


def test_setup_status_reports_needs_setup_false_once_an_admin_exists(client: TestClient) -> None:
    response = client.get("/api/v1/auth/setup-status")
    assert response.status_code == 200
    assert response.json() == {"needs_setup": False}


def test_bootstrap_admin_succeeds_and_returns_tokens_when_no_admin_exists() -> None:
    empty_client, _ = _empty_client()

    response = empty_client.post(
        "/api/v1/auth/bootstrap-admin",
        json={"email": "first-admin@example.com", "password": "S0meStrongPass!"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]

    # The new access token really identifies an ADMIN now.
    me_response = empty_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me_response.status_code == 200
    assert me_response.json()["role"] == "ADMIN"
    assert me_response.json()["email"] == "first-admin@example.com"


def test_bootstrap_admin_fails_once_an_admin_already_exists(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/bootstrap-admin",
        json={"email": "second-admin@example.com", "password": "S0meStrongPass!"},
    )
    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")


def test_bootstrap_admin_rejects_a_short_password() -> None:
    empty_client, _ = _empty_client()

    response = empty_client.post(
        "/api/v1/auth/bootstrap-admin",
        json={"email": "first-admin@example.com", "password": "short"},
    )
    assert response.status_code == 422


def test_forgot_password_returns_generic_message_for_unknown_email(
    client: TestClient, token_repo: FakePasswordResetTokenRepository, monkeypatch
) -> None:
    sent = []
    monkeypatch.setattr(
        auth_service, "send_password_reset_email", lambda **kwargs: sent.append(kwargs)
    )

    response = client.post("/api/v1/auth/forgot-password", json={"email": "ghost@example.com"})
    assert response.status_code == 200
    assert sent == []
    assert token_repo._by_id == {}


def test_forgot_password_sends_email_and_returns_same_message_for_known_email(
    client: TestClient, token_repo: FakePasswordResetTokenRepository, monkeypatch
) -> None:
    sent = []
    monkeypatch.setattr(
        auth_service, "send_password_reset_email", lambda **kwargs: sent.append(kwargs)
    )

    known_response = client.post(
        "/api/v1/auth/forgot-password", json={"email": "admin@example.com"}
    )
    unknown_response = client.post(
        "/api/v1/auth/forgot-password", json={"email": "ghost@example.com"}
    )

    assert known_response.status_code == 200 == unknown_response.status_code
    # Identical body either way -- no leak of whether the email exists.
    assert known_response.json() == unknown_response.json()
    assert len(sent) == 1
    assert len(token_repo._by_id) == 1


def test_reset_password_succeeds_and_new_password_can_log_in(
    client: TestClient, monkeypatch
) -> None:
    # The plaintext reset token only ever exists inside the `reset_url` this
    # service call would otherwise email out -- capture it here instead of a
    # real SMTP send.
    reset_url_holder: dict[str, str] = {}
    monkeypatch.setattr(
        auth_service,
        "send_password_reset_email",
        lambda **kwargs: reset_url_holder.update(reset_url=kwargs["reset_url"]),
    )
    client.post("/api/v1/auth/forgot-password", json={"email": "admin@example.com"})
    plaintext_token = reset_url_holder["reset_url"].rsplit("token=", 1)[1]

    response = client.post(
        "/api/v1/auth/reset-password",
        json={"token": plaintext_token, "new_password": "BrandNewPass!1"},
    )
    assert response.status_code == 200

    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "BrandNewPass!1"},
    )
    assert login_response.status_code == 200


def test_reset_password_rejects_an_invalid_token(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/reset-password",
        json={"token": "not-a-real-token", "new_password": "BrandNewPass!1"},
    )
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")


def test_reset_password_rejects_a_short_new_password(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/reset-password", json={"token": "irrelevant.token", "new_password": "short"}
    )
    assert response.status_code == 422
