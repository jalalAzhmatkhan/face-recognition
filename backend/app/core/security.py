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

import secrets
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


def hash_secret(plain_secret: str) -> str:
    """Alias of `hash_password` for non-password secrets (BE-09 device
    credentials). Argon2id has no reason to differ by "kind" of secret —
    kept as a distinct name at call sites purely for readability."""
    return _hasher.hash(plain_secret)


def verify_secret(plain_secret: str, secret_hash: str) -> bool:
    """Alias of `verify_password` for non-password secrets (BE-09)."""
    return verify_password(plain_secret, secret_hash)


def generate_device_credential() -> tuple[str, str, str]:
    """Generate a new per-device token credential (BE-09, NFR-SEC-04).

    Returns `(credential_id, plaintext_secret, plaintext_token)`:
    - `credential_id`: short, non-secret, URL/DB-safe identifier used to
      look a device up by presented token (stored in
      `devices.auth_credential_ref`, UNIQUE).
    - `plaintext_secret`: the actual high-entropy secret. Only its Argon2id
      hash (`hash_secret`) is ever persisted (`devices.credential_hash`).
    - `plaintext_token`: `f"{credential_id}.{plaintext_secret}"` — the
      single string returned to the API caller exactly once (POST
      /devices or POST /devices/{id}/rotate-credential response body) and
      never stored anywhere in plaintext. The device presents this same
      string as its bearer token on subsequent calls (e.g. heartbeat).

    Design note: this is a simpler, non-mTLS substitute for the "per-device
    credential / mTLS token" NFR-SEC-04 calls for — same simplification
    philosophy as staff JWT auth standing in for full OIDC (see
    app/core/security.py module docstring). Real X.509/mTLS device
    provisioning is out of scope for v1 (BE-09 task instructions).
    """
    credential_id = secrets.token_hex(8)  # 16 hex chars — non-secret lookup key
    plaintext_secret = secrets.token_urlsafe(32)  # ~256 bits of entropy
    plaintext_token = format_device_token(credential_id, plaintext_secret)
    return credential_id, plaintext_secret, plaintext_token


def format_device_token(credential_id: str, plaintext_secret: str) -> str:
    return f"{credential_id}.{plaintext_secret}"


def parse_device_token(token: str) -> tuple[str, str] | None:
    """Split a presented device bearer token into `(credential_id, secret)`.

    Returns `None` (never raises) for any malformed token — callers must
    treat that identically to "credential not found" so a malformed vs.
    unknown token can't be distinguished by an attacker (NFR-SEC-04)."""
    credential_id, sep, secret = token.partition(".")
    if not sep or not credential_id or not secret:
        return None
    return credential_id, secret


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
