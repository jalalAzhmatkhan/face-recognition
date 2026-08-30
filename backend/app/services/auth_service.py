"""AuthN business logic for staff login/refresh (BE-03, FR-USR-02, NFR-SEC-04).

Depends on a `StaffAccountReader` protocol (not the concrete repository)
so unit tests can supply a fake in-memory repository without a real DB
session — see backend/tests/test_auth_service.py.
"""

import uuid
from typing import Protocol

from app.core.config import Settings, get_settings
from app.core.security import (
    TokenError,
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.models.staff_account import StaffAccount


class StaffAccountReader(Protocol):
    def get(self, staff_id: uuid.UUID) -> StaffAccount | None: ...
    def get_by_email(self, email: str) -> StaffAccount | None: ...


class InvalidCredentialsError(Exception):
    """Login failed. Deliberately generic — never says *why* (NFR-SEC-04:
    must not reveal whether the email exists)."""


class InvalidRefreshTokenError(Exception):
    """Refresh token missing/expired/invalid, or points at a staff account
    that no longer exists."""


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


# A real argon2 hash of a random, never-used password — exists purely so
# `authenticate()` always pays the same hashing cost whether or not the
# account exists. Regenerate freely; the plaintext behind it is discarded.
_DUMMY_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$wLbA1NRP4DE1tJ9v7o380Q$"
    "wZ/8vMBtIjqfO0EftopO+2wALDPGaSlVU93BLSKLLRE"
)
