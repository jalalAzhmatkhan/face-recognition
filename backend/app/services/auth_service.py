"""AuthN business logic for staff login/refresh (BE-03, FR-USR-02, NFR-SEC-04).

Depends on a `StaffAccountReader` protocol (not the concrete repository)
so unit tests can supply a fake in-memory repository without a real DB
session — see backend/tests/test_auth_service.py.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Protocol

from app.core.config import Settings, get_settings
from app.core.security import (
    TokenError,
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_password_reset_token,
    hash_password,
    hash_secret,
    parse_password_reset_token,
    verify_password,
    verify_secret,
)
from app.models.enums import StaffRole
from app.models.password_reset_token import PasswordResetToken
from app.models.staff_account import StaffAccount
from app.services.email_service import send_password_reset_email


class StaffAccountReader(Protocol):
    def get(self, staff_id: uuid.UUID) -> StaffAccount | None: ...
    def get_by_email(self, email: str) -> StaffAccount | None: ...


class StaffAccountBootstrapper(Protocol):
    def exists_by_role(self, role: StaffRole) -> bool: ...
    def create(self, account: StaffAccount) -> StaffAccount: ...


class PasswordResetStaffRepo(Protocol):
    def get(self, staff_id: uuid.UUID) -> StaffAccount | None: ...
    def get_by_email(self, email: str) -> StaffAccount | None: ...
    def update_password_hash(self, account: StaffAccount, password_hash: str) -> None: ...


class PasswordResetTokenStore(Protocol):
    def get(self, token_id: uuid.UUID) -> PasswordResetToken | None: ...
    def create(self, token: PasswordResetToken) -> PasswordResetToken: ...
    def mark_used(self, token: PasswordResetToken) -> None: ...


class InvalidCredentialsError(Exception):
    """Login failed. Deliberately generic — never says *why* (NFR-SEC-04:
    must not reveal whether the email exists)."""


class InvalidRefreshTokenError(Exception):
    """Refresh token missing/expired/invalid, or points at a staff account
    that no longer exists."""


class AdminAlreadyExistsError(Exception):
    """`bootstrap_admin` is a one-time-only operation — raised when at least
    one ADMIN account already exists."""


class InvalidResetTokenError(Exception):
    """Reset token missing/malformed/expired/already-used/unknown — all
    treated identically (NFR-SEC-04: no info leak about which)."""


def authenticate(
    repo: StaffAccountReader, *, email: str, password: str
) -> StaffAccount:
    """Verify email+password. Raises `InvalidCredentialsError` on any failure.

    Runs `verify_password` against a fixed dummy hash when the account is
    missing so a non-existent email takes roughly the same time as a wrong
    password (mitigates a coarse timing side-channel + guarantees the code
    path — and therefore the exact response — is identical either way).
    """
    account = repo.get_by_email(email)
    password_hash = account.password_hash if account is not None else _DUMMY_HASH

    if password_hash is None or not verify_password(password, password_hash):
        raise InvalidCredentialsError("Invalid email or password")
    if account is None:
        # Unreachable in practice (password_hash would be _DUMMY_HASH, which
        # never verifies), kept as an explicit guard for type-narrowing.
        raise InvalidCredentialsError("Invalid email or password")
    return account


def issue_tokens(
    account: StaffAccount, *, settings: Settings | None = None
) -> tuple[str, str, int]:
    """Returns (access_token, refresh_token, expires_in_seconds)."""
    settings = settings or get_settings()
    access_token, expires_in = create_access_token(
        staff_id=account.id, role=account.role.value, settings=settings
    )
    refresh_token = create_refresh_token(staff_id=account.id, settings=settings)
    return access_token, refresh_token, expires_in


def refresh_access_token(
    repo: StaffAccountReader, *, refresh_token: str, settings: Settings | None = None
) -> tuple[str, int]:
    """Validate a refresh token and mint a new access token.

    Minimal rotation per task scope: the refresh token itself is NOT rotated
    (same refresh token remains valid until its own expiry) — only a fresh,
    short-lived access token is issued. Raises `InvalidRefreshTokenError` on
    any problem (expired/invalid/wrong-type token, or account no longer
    exists e.g. offboarded staff).
    """
    settings = settings or get_settings()
    try:
        payload = decode_token(refresh_token, expected_type=TokenType.REFRESH, settings=settings)
    except TokenError as exc:
        raise InvalidRefreshTokenError(str(exc)) from exc

    try:
        staff_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise InvalidRefreshTokenError("Malformed token subject") from exc

    account = repo.get(staff_id)
    if account is None:
        raise InvalidRefreshTokenError("Staff account no longer exists")

    access_token, expires_in = create_access_token(
        staff_id=account.id, role=account.role.value, settings=settings
    )
    return access_token, expires_in


def needs_admin_bootstrap(repo: StaffAccountBootstrapper) -> bool:
    """True while zero ADMIN accounts exist anywhere -- the only time the
    first-run bootstrap screen/endpoint should be usable."""
    return not repo.exists_by_role(StaffRole.ADMIN)


def bootstrap_admin(
    repo: StaffAccountBootstrapper, *, email: str, password: str
) -> StaffAccount:
    """Create the very first ADMIN account. Raises `AdminAlreadyExistsError`
    if one already exists -- this is intentionally NOT a general-purpose
    "create staff account" function (no such HTTP endpoint exists yet, see
    `app/cli.py::create_admin` for the CLI equivalent used by seed/dev
    scripts); it exists solely to unblock a freshly-deployed instance with
    no staff accounts at all.

    Known limitation: the exists-then-create check is not atomic against a
    concurrent call (no unique constraint on `role`, no row lock) -- a race
    could create two ADMINs. Acceptable for a one-time, human-triggered,
    first-run action; no such concurrency guard exists elsewhere in this
    codebase either (see `StaffAccountRepository` docstring).
    """
    if repo.exists_by_role(StaffRole.ADMIN):
        raise AdminAlreadyExistsError("An ADMIN account already exists.")

    account = StaffAccount(email=email, role=StaffRole.ADMIN, password_hash=hash_password(password))
    return repo.create(account)


def request_password_reset(
    staff_repo: PasswordResetStaffRepo,
    token_repo: PasswordResetTokenStore,
    *,
    email: str,
    settings: Settings | None = None,
) -> None:
    """Always succeeds from the caller's perspective (NFR-SEC-04: the
    `/auth/forgot-password` response must not reveal whether `email`
    matched an account) — silently does nothing when there's no match.
    Mints a single-use token and emails a reset link otherwise.
    """
    settings = settings or get_settings()
    account = staff_repo.get_by_email(email)
    if account is None:
        return

    token_id, plaintext_secret, plaintext_token = generate_password_reset_token()
    expires_at = datetime.now(UTC) + timedelta(
        minutes=settings.password_reset_token_expire_minutes
    )
    token_repo.create(
        PasswordResetToken(
            id=token_id,
            staff_id=account.id,
            token_hash=hash_secret(plaintext_secret),
            expires_at=expires_at,
        )
    )
    reset_url = f"{settings.frontend_base_url}/reset-password?token={plaintext_token}"
    send_password_reset_email(to_address=account.email, reset_url=reset_url, settings=settings)


def reset_password(
    staff_repo: PasswordResetStaffRepo,
    token_repo: PasswordResetTokenStore,
    *,
    token: str,
    new_password: str,
) -> None:
    """Validate a presented `<token_id>.<secret>` reset token and, if valid,
    update the target account's password and consume the token. Raises
    `InvalidResetTokenError` for anything malformed/unknown/expired/already
    used/pointing at a missing account — deliberately the same exception
    for all of these (NFR-SEC-04).
    """
    parsed = parse_password_reset_token(token)
    if parsed is None:
        raise InvalidResetTokenError("Malformed reset token")
    token_id, secret = parsed

    record = token_repo.get(token_id)
    if record is None or record.used_at is not None:
        raise InvalidResetTokenError("Invalid or already-used reset token")
    if record.expires_at <= datetime.now(UTC):
        raise InvalidResetTokenError("Reset token has expired")
    if not verify_secret(secret, record.token_hash):
        raise InvalidResetTokenError("Invalid reset token")

    account = staff_repo.get(record.staff_id)
    if account is None:
        raise InvalidResetTokenError("Invalid reset token")

    staff_repo.update_password_hash(account, hash_password(new_password))
    token_repo.mark_used(record)


# A real argon2 hash of a random, never-used password — exists purely so
# `authenticate()` always pays the same hashing cost whether or not the
# account exists. Regenerate freely; the plaintext behind it is discarded.
_DUMMY_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$wLbA1NRP4DE1tJ9v7o380Q$"
    "wZ/8vMBtIjqfO0EftopO+2wALDPGaSlVU93BLSKLLRE"
)
