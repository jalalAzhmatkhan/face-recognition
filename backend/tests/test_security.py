"""Unit tests for app/core/security.py — hashing + JWT (BE-03).

Pure unit tests, no DB involved.
"""

import uuid
from datetime import timedelta

import jwt
import pytest

from app.core.config import Settings
from app.core.security import (
    TokenError,
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def _settings(**overrides) -> Settings:
    overrides.setdefault("jwt_secret_key", "unit-test-secret")
    return Settings(**overrides)


def test_hash_password_produces_a_verifiable_but_different_string() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed)


def test_verify_password_rejects_wrong_password() -> None:
    hashed = hash_password("correct horse battery staple")
    assert not verify_password("wrong password", hashed)


def test_verify_password_never_raises_on_garbage_hash() -> None:
    assert not verify_password("anything", "not-a-real-argon2-hash")


def test_access_token_round_trips_and_carries_role_claim() -> None:
    settings = _settings()
    staff_id = uuid.uuid4()
    token, expires_in = create_access_token(staff_id=staff_id, role="ADMIN", settings=settings)

    payload = decode_token(token, expected_type=TokenType.ACCESS, settings=settings)
    assert payload["sub"] == str(staff_id)
    assert payload["role"] == "ADMIN"
    assert expires_in == settings.access_token_expire_minutes * 60


def test_refresh_token_round_trips() -> None:
    settings = _settings()
    staff_id = uuid.uuid4()
    token = create_refresh_token(staff_id=staff_id, settings=settings)

    payload = decode_token(token, expected_type=TokenType.REFRESH, settings=settings)
    assert payload["sub"] == str(staff_id)


def test_access_token_rejected_when_decoded_as_refresh() -> None:
    settings = _settings()
    token, _ = create_access_token(staff_id=uuid.uuid4(), role="VIEWER", settings=settings)

    with pytest.raises(TokenError):
        decode_token(token, expected_type=TokenType.REFRESH, settings=settings)


def test_expired_token_is_rejected() -> None:
    settings = _settings()
    # Encode directly with a negative expiry to simulate an already-expired token
    # (create_access_token always uses the configured positive expiry).
    from datetime import UTC, datetime

    payload = {
        "sub": str(uuid.uuid4()),
        "type": TokenType.ACCESS.value,
        "iat": datetime.now(UTC) - timedelta(minutes=30),
        "exp": datetime.now(UTC) - timedelta(minutes=15),
    }
    expired_token = jwt.encode(
        payload, settings.jwt_secret_key.get_secret_value(), algorithm=settings.jwt_algorithm
    )

    with pytest.raises(TokenError):
        decode_token(expired_token, expected_type=TokenType.ACCESS, settings=settings)


def test_token_signed_with_different_secret_is_rejected() -> None:
    settings_a = _settings(jwt_secret_key="secret-a")
    settings_b = _settings(jwt_secret_key="secret-b")
    token, _ = create_access_token(staff_id=uuid.uuid4(), role="OPERATOR", settings=settings_a)

    with pytest.raises(TokenError):
        decode_token(token, expected_type=TokenType.ACCESS, settings=settings_b)
