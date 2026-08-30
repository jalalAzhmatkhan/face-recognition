"""Password hashing + JWT issuing/verification for staff AuthN (BE-03, NFR-SEC-04).

Library choices (documented per task instructions):
- Password hashing: **argon2-cffi** (Argon2id). Chosen over passlib+bcrypt
  because Argon2id is the current OWASP-recommended default, has no 72-byte
  input truncation footgun (bcrypt does), and avoids the passlib/bcrypt
  version-compatibility breakage seen with bcrypt>=4.1. Used directly (not
  via passlib) to keep the dependency surface small.
- JWT: **PyJWT**. Simpler API and more actively maintained than
  `python-jose` (which has had unresolved CVEs) for the HS256-only use case
  needed here.
"""

import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import Settings, get_settings

_hasher = PasswordHasher()


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


class TokenError(Exception):
    """Raised for any invalid/expired/malformed JWT — callers map this to 401."""


def hash_password(plain_password: str) -> str:
    return _hasher.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Constant-time-ish verify; any failure (mismatch, bad hash) -> False.

    Never raises — callers must not be able to distinguish "wrong password"
    from "malformed hash" from exception type (NFR-SEC-04: no info leak).
    """
    try:
        return _hasher.verify(password_hash, plain_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def _encode(
    *,
    subject: str,
    token_type: TokenType,
    expires_delta: timedelta,
    settings: Settings,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type.value,
        "iat": now,
        "exp": now + expires_delta,
        "jti": str(uuid.uuid4()),
    }
    if extra_claims:
        payload.update(extra_claims)
    secret = settings.jwt_secret_key.get_secret_value()
    return jwt.encode(payload, secret, algorithm=settings.jwt_algorithm)


def create_access_token(
    *, staff_id: uuid.UUID, role: str, settings: Settings | None = None
) -> tuple[str, int]:
    settings = settings or get_settings()
    expires_delta = timedelta(minutes=settings.access_token_expire_minutes)
    token = _encode(
        subject=str(staff_id),
        token_type=TokenType.ACCESS,
        expires_delta=expires_delta,
        settings=settings,
        extra_claims={"role": role},
    )
    return token, int(expires_delta.total_seconds())


def create_refresh_token(*, staff_id: uuid.UUID, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    expires_delta = timedelta(minutes=settings.refresh_token_expire_minutes)
    return _encode(
        subject=str(staff_id),
        token_type=TokenType.REFRESH,
        expires_delta=expires_delta,
        settings=settings,
    )


def decode_token(
    token: str, *, expected_type: TokenType, settings: Settings | None = None
) -> dict[str, Any]:
    """Decode+validate a JWT, raising `TokenError` on any problem.

    Callers must pass `expected_type` so an access token can never be used
    where a refresh token is required and vice versa.
    """
    settings = settings or get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.PyJWTError as exc:
        raise TokenError("Invalid or expired token") from exc

    if payload.get("type") != expected_type.value:
        raise TokenError("Unexpected token type")
    if "sub" not in payload:
        raise TokenError("Token missing subject")
    return payload
