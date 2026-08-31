"""Unit tests for `ai_inference.device_auth` (IN-02, NFR-SEC-04).

Must pass on base CI (no `ml` extra) -- argon2-cffi is a base dependency
(see pyproject.toml), and this module only needs a fake DB-API cursor
(mirrors the FakeCursor idiom in `tests/test_gallery.py`), no real Postgres.
"""

import uuid

import pytest
from argon2 import PasswordHasher

from ai_inference import device_auth

_hasher = PasswordHasher()


class FakeCursor:
    """Dispatches on query prefix; holds at most one `devices` row."""

    def __init__(self, *, row: tuple[str, str, str] | None) -> None:
        self.row = row
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, query: str, params: tuple = ()) -> None:
        self.executed.append((query, params))

    def fetchone(self):
        return self.row


# --- parse_device_token ------------------------------------------------


def test_parse_device_token_valid() -> None:
    assert device_auth.parse_device_token("abc123.supersecret") == ("abc123", "supersecret")


def test_parse_device_token_secret_can_contain_dots() -> None:
    # partition() splits on the FIRST "." only, so a secret containing "."
    # stays intact as the second half.
    assert device_auth.parse_device_token("abc123.super.secret") == ("abc123", "super.secret")


def test_parse_device_token_no_dot_is_malformed() -> None:
    assert device_auth.parse_device_token("nodothere") is None


def test_parse_device_token_leading_dot_is_malformed() -> None:
    assert device_auth.parse_device_token(".secretonly") is None


def test_parse_device_token_trailing_dot_is_malformed() -> None:
    assert device_auth.parse_device_token("credentialonly.") is None


def test_parse_device_token_empty_string_is_malformed() -> None:
    assert device_auth.parse_device_token("") is None


# --- verify_secret -------------------------------------------------------


def test_verify_secret_matches() -> None:
    secret_hash = _hasher.hash("correct-horse-battery-staple")
    assert device_auth.verify_secret("correct-horse-battery-staple", secret_hash) is True


def test_verify_secret_mismatch() -> None:
    secret_hash = _hasher.hash("correct-horse-battery-staple")
    assert device_auth.verify_secret("wrong-secret", secret_hash) is False


def test_verify_secret_corrupt_hash_never_raises() -> None:
    assert device_auth.verify_secret("anything", "not-a-real-argon2-hash") is False


# --- get_device_by_credential_id -----------------------------------------


def test_get_device_by_credential_id_found_coerces_to_str() -> None:
    device_id = uuid.uuid4()
    cursor = FakeCursor(row=(device_id, "hash", "ONLINE"))
    result = device_auth.get_device_by_credential_id(cursor, "cred-1")
    assert result == (str(device_id), "hash", "ONLINE")
    assert isinstance(result[0], str)


def test_get_device_by_credential_id_not_found() -> None:
    cursor = FakeCursor(row=None)
    assert device_auth.get_device_by_credential_id(cursor, "cred-missing") is None


def test_get_device_by_credential_id_query_scoped_to_devices_only() -> None:
    cursor = FakeCursor(row=None)
    device_auth.get_device_by_credential_id(cursor, "cred-1")
    query, params = cursor.executed[0]
    assert "FROM devices" in query
    assert "WHERE auth_credential_ref = %s" in query
    assert params == ("cred-1",)


# --- authenticate_device ---------------------------------------------------


def _hashed(secret: str) -> str:
    return _hasher.hash(secret)


def test_authenticate_device_malformed_token() -> None:
    cursor = FakeCursor(row=None)
    with pytest.raises(device_auth.InvalidDeviceCredentialError):
        device_auth.authenticate_device(cursor, "no-dot-here")
    # Malformed token means we never even queried the DB.
    assert cursor.executed == []


def test_authenticate_device_unknown_credential() -> None:
    cursor = FakeCursor(row=None)
    with pytest.raises(device_auth.InvalidDeviceCredentialError):
        device_auth.authenticate_device(cursor, "cred-1.some-secret")


def test_authenticate_device_wrong_secret() -> None:
    cursor = FakeCursor(row=(uuid.uuid4(), _hashed("correct-secret"), "ONLINE"))
    with pytest.raises(device_auth.InvalidDeviceCredentialError):
        device_auth.authenticate_device(cursor, "cred-1.wrong-secret")


def test_authenticate_device_disabled() -> None:
    device_id = uuid.uuid4()
    cursor = FakeCursor(row=(device_id, _hashed("correct-secret"), "DISABLED"))
    with pytest.raises(device_auth.DeviceDisabledError) as exc_info:
        device_auth.authenticate_device(cursor, "cred-1.correct-secret")
    assert exc_info.value.device_id == str(device_id)


def test_authenticate_device_success() -> None:
    device_id = uuid.uuid4()
    cursor = FakeCursor(row=(device_id, _hashed("correct-secret"), "ONLINE"))
    result = device_auth.authenticate_device(cursor, "cred-1.correct-secret")
    assert result == str(device_id)
