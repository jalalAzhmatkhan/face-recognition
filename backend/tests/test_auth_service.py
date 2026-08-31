"""Unit tests for app/services/auth_service.py (BE-03).

Uses a fake in-memory repository (matches the `StaffAccountReader` protocol)
instead of a real DB session/engine — no live Postgres needed.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import Settings
from app.core.security import create_refresh_token, hash_password, hash_secret, verify_password
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
        # See matching comment in tests/test_auth_router.py's fake.
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


def _settings() -> Settings:
    return Settings(jwt_secret_key="unit-test-secret")


def _account(
    *, email: str = "admin@example.com", password: str = "S0meStrongPass!"
) -> StaffAccount:
    return StaffAccount(
        id=uuid.uuid4(),
        email=email,
        role=StaffRole.ADMIN,
        password_hash=hash_password(password),
    )


def test_authenticate_succeeds_with_correct_credentials() -> None:
    account = _account()
    repo = FakeStaffAccountRepository([account])

    result = auth_service.authenticate(repo, email=account.email, password="S0meStrongPass!")
    assert result.id == account.id


def test_authenticate_fails_with_wrong_password() -> None:
    account = _account()
    repo = FakeStaffAccountRepository([account])

    with pytest.raises(auth_service.InvalidCredentialsError):
        auth_service.authenticate(repo, email=account.email, password="wrong-password")


def test_authenticate_fails_with_nonexistent_user_using_identical_error() -> None:
    repo = FakeStaffAccountRepository([])

    with pytest.raises(auth_service.InvalidCredentialsError) as exc_info_missing:
        auth_service.authenticate(repo, email="ghost@example.com", password="whatever")

    account = _account()
    repo_with_account = FakeStaffAccountRepository([account])
    with pytest.raises(auth_service.InvalidCredentialsError) as exc_info_wrong_pw:
        auth_service.authenticate(repo_with_account, email=account.email, password="wrong")

    # Same exception message either way — callers (the router) must not be
    # able to tell "no such user" from "wrong password" apart (NFR-SEC-04).
    assert str(exc_info_missing.value) == str(exc_info_wrong_pw.value)


def test_authenticate_fails_for_account_with_no_password_set() -> None:
    """An OIDC-only account (future phase) has no local password — must not
    be logged into via this endpoint."""
    account = StaffAccount(
        id=uuid.uuid4(), email="oidc-only@example.com", role=StaffRole.VIEWER, password_hash=None
    )
    repo = FakeStaffAccountRepository([account])

    with pytest.raises(auth_service.InvalidCredentialsError):
        auth_service.authenticate(repo, email=account.email, password="anything")


def test_refresh_access_token_succeeds_for_valid_token() -> None:
    settings = _settings()
    account = _account()
    repo = FakeStaffAccountRepository([account])
    refresh_token = create_refresh_token(staff_id=account.id, settings=settings)

    access_token, expires_in = auth_service.refresh_access_token(
        repo, refresh_token=refresh_token, settings=settings
    )
    assert access_token
    assert expires_in == settings.access_token_expire_minutes * 60


def test_refresh_access_token_rejects_invalid_token() -> None:
    repo = FakeStaffAccountRepository([])

    with pytest.raises(auth_service.InvalidRefreshTokenError):
        auth_service.refresh_access_token(repo, refresh_token="not-a-jwt")


def test_refresh_access_token_rejects_access_token_used_as_refresh() -> None:
    from app.core.security import create_access_token

    settings = _settings()
    account = _account()
    repo = FakeStaffAccountRepository([account])
    access_token, _ = create_access_token(staff_id=account.id, role="ADMIN", settings=settings)

    with pytest.raises(auth_service.InvalidRefreshTokenError):
        auth_service.refresh_access_token(repo, refresh_token=access_token, settings=settings)


def test_refresh_access_token_rejects_when_account_no_longer_exists() -> None:
    settings = _settings()
    refresh_token = create_refresh_token(staff_id=uuid.uuid4(), settings=settings)
    repo = FakeStaffAccountRepository([])  # account deleted/offboarded

    with pytest.raises(auth_service.InvalidRefreshTokenError):
        auth_service.refresh_access_token(repo, refresh_token=refresh_token, settings=settings)


def test_needs_admin_bootstrap_true_with_no_accounts() -> None:
    repo = FakeStaffAccountRepository([])
    assert auth_service.needs_admin_bootstrap(repo) is True


def test_needs_admin_bootstrap_false_once_an_admin_exists() -> None:
    repo = FakeStaffAccountRepository([_account()])
    assert auth_service.needs_admin_bootstrap(repo) is False


def test_needs_admin_bootstrap_true_with_only_non_admin_accounts() -> None:
    viewer = StaffAccount(
        id=uuid.uuid4(),
        email="viewer@example.com",
        role=StaffRole.VIEWER,
        password_hash=hash_password("whatever123"),
    )
    repo = FakeStaffAccountRepository([viewer])
    assert auth_service.needs_admin_bootstrap(repo) is True


def test_bootstrap_admin_creates_an_admin_account_when_none_exists() -> None:
    repo = FakeStaffAccountRepository([])

    account = auth_service.bootstrap_admin(
        repo, email="first-admin@example.com", password="S0meStrongPass!"
    )
    assert account.role == StaffRole.ADMIN
    assert account.email == "first-admin@example.com"
    assert repo.get_by_email("first-admin@example.com") is account


def test_bootstrap_admin_rejects_when_an_admin_already_exists() -> None:
    repo = FakeStaffAccountRepository([_account()])

    with pytest.raises(auth_service.AdminAlreadyExistsError):
        auth_service.bootstrap_admin(
            repo, email="second-admin@example.com", password="S0meStrongPass!"
        )


def test_request_password_reset_does_nothing_for_an_unknown_email(monkeypatch) -> None:
    sent = []
    monkeypatch.setattr(
        auth_service, "send_password_reset_email", lambda **kwargs: sent.append(kwargs)
    )
    staff_repo = FakeStaffAccountRepository([])
    token_repo = FakePasswordResetTokenRepository()

    auth_service.request_password_reset(staff_repo, token_repo, email="ghost@example.com")

    assert sent == []
    assert token_repo._by_id == {}


def test_request_password_reset_mints_a_token_and_sends_email(monkeypatch) -> None:
    sent = []
    monkeypatch.setattr(
        auth_service, "send_password_reset_email", lambda **kwargs: sent.append(kwargs)
    )
    account = _account(email="admin@example.com")
    staff_repo = FakeStaffAccountRepository([account])
    token_repo = FakePasswordResetTokenRepository()

    auth_service.request_password_reset(staff_repo, token_repo, email="admin@example.com")

    assert len(sent) == 1
    assert sent[0]["to_address"] == "admin@example.com"
    assert "reset_url" in sent[0]
    assert len(token_repo._by_id) == 1
    (token,) = token_repo._by_id.values()
    assert token.staff_id == account.id
    assert token.used_at is None


def _reset_token(*, staff_id: uuid.UUID, secret: str = "reset-secret", expired: bool = False):
    token_id = uuid.uuid4()
    expires_at = datetime.now(UTC) + (
        timedelta(minutes=-1) if expired else timedelta(minutes=30)
    )
    return token_id, PasswordResetToken(
        id=token_id,
        staff_id=staff_id,
        token_hash=hash_secret(secret),
        expires_at=expires_at,
    )


def test_reset_password_succeeds_with_a_valid_token() -> None:
    account = _account()
    staff_repo = FakeStaffAccountRepository([account])
    token_repo = FakePasswordResetTokenRepository()
    token_id, record = _reset_token(staff_id=account.id, secret="reset-secret")
    token_repo.create(record)

    auth_service.reset_password(
        staff_repo, token_repo, token=f"{token_id}.reset-secret", new_password="NewStrongPass!1"
    )

    assert verify_password("NewStrongPass!1", account.password_hash)
    assert record.used_at is not None


def test_reset_password_rejects_a_malformed_token() -> None:
    staff_repo = FakeStaffAccountRepository([])
    token_repo = FakePasswordResetTokenRepository()

    with pytest.raises(auth_service.InvalidResetTokenError):
        auth_service.reset_password(
            staff_repo, token_repo, token="not-a-valid-token", new_password="NewStrongPass!1"
        )


def test_reset_password_rejects_an_unknown_token_id() -> None:
    staff_repo = FakeStaffAccountRepository([])
    token_repo = FakePasswordResetTokenRepository()

    with pytest.raises(auth_service.InvalidResetTokenError):
        auth_service.reset_password(
            staff_repo,
            token_repo,
            token=f"{uuid.uuid4()}.some-secret",
            new_password="NewStrongPass!1",
        )


def test_reset_password_rejects_an_expired_token() -> None:
    account = _account()
    staff_repo = FakeStaffAccountRepository([account])
    token_repo = FakePasswordResetTokenRepository()
    token_id, record = _reset_token(staff_id=account.id, secret="reset-secret", expired=True)
    token_repo.create(record)

    with pytest.raises(auth_service.InvalidResetTokenError):
        auth_service.reset_password(
            staff_repo, token_repo, token=f"{token_id}.reset-secret", new_password="NewStrongPass!1"
        )


def test_reset_password_rejects_a_wrong_secret() -> None:
    account = _account()
    staff_repo = FakeStaffAccountRepository([account])
    token_repo = FakePasswordResetTokenRepository()
    token_id, record = _reset_token(staff_id=account.id, secret="reset-secret")
    token_repo.create(record)

    with pytest.raises(auth_service.InvalidResetTokenError):
        auth_service.reset_password(
            staff_repo, token_repo, token=f"{token_id}.wrong-secret", new_password="NewStrongPass!1"
        )


def test_reset_password_rejects_reusing_an_already_used_token() -> None:
    account = _account()
    staff_repo = FakeStaffAccountRepository([account])
    token_repo = FakePasswordResetTokenRepository()
    token_id, record = _reset_token(staff_id=account.id, secret="reset-secret")
    token_repo.create(record)

    auth_service.reset_password(
        staff_repo, token_repo, token=f"{token_id}.reset-secret", new_password="NewStrongPass!1"
    )
    with pytest.raises(auth_service.InvalidResetTokenError):
        auth_service.reset_password(
            staff_repo, token_repo, token=f"{token_id}.reset-secret", new_password="AnotherPass!2"
        )
