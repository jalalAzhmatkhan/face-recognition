"""Device credential AuthN for `/recognize` (IN-02, NFR-SEC-04).

Closes the gap `ai_inference.main`'s `/recognize` endpoint used to document
("IN-02 GAP: this endpoint has NO authentication at all"): every request now
must present a bearer token of the form ``<credential_id>.<secret>``,
verified against the `devices` table's `auth_credential_ref`/
`credential_hash`/`status` columns via the read-only `ai_inference_ro`
Postgres role (migration `d4e8a2f6c1b9`).

**Why this duplicates backend code instead of importing it** (deliberate,
documented trade-off -- see IN-02 task brief): `backend/app/core/security.py`
(`parse_device_token`/`verify_secret`) and
`backend/app/services/device_service.py::authenticate_device` already
implement this exact scheme for BE-09's own device-facing routes (e.g.
heartbeat). `ai-inference` does NOT import from `backend/` -- unlike the
`ai-training` path dependency (shared ML/pipeline code, a genuinely common
concern), staff/device authentication is backend's own concern, and importing
it here would blur the service boundary and couple this service's dependency
graph to the entire backend app (FastAPI app, SQLAlchemy models, alembic,
...) just to reuse ~30 lines of Argon2id + string-splitting logic. So this
module re-implements that logic in miniature, directly against a raw
DB-API cursor (mirroring `ai_inference.gallery`'s pattern) rather than
SQLAlchemy models, with the same security invariants:

- `parse_device_token` never raises, returns `None` for anything malformed.
- `verify_secret` never raises, returns `False` for any mismatch or corrupt
  hash.
- Every credential-related failure (malformed token, unknown credential_id,
  wrong secret) raises the SAME `InvalidDeviceCredentialError` with a
  generic message, so a caller-facing 401 can never be used to distinguish
  "no such device" from "wrong secret" (NFR-SEC-04: no info leak). Only a
  device that authenticates successfully but is administratively DISABLED
  gets the distinct `DeviceDisabledError` (-> 403 at the dependency layer).

`argon2-cffi` is a base (non-`ml`-extra) dependency of this package
specifically so device auth works, and is unit-testable, without the heavy
`ml` extra installed -- see `pyproject.toml`.
"""

from __future__ import annotations

from typing import Any, Protocol

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()


class Cursor(Protocol):
    def execute(self, query: str, params: tuple[Any, ...] = ()) -> Any: ...
    def fetchone(self) -> tuple[Any, ...] | None: ...


class InvalidDeviceCredentialError(Exception):
    """Presented device bearer token does not resolve to a known, valid
    credential -- raised for EVERY failure mode (malformed token, unknown
    credential_id, wrong secret) so callers can never distinguish them from
    the exception alone (NFR-SEC-04). Maps to 401 at the dependency layer."""


class DeviceDisabledError(Exception):
    """Credential is valid but the device's `status` is `DISABLED`. A
    distinct, non-secret-leaking condition worth a different HTTP status
    (403) at the dependency layer."""

    def __init__(self, device_id: str) -> None:
        self.device_id = device_id
        super().__init__(device_id)


def parse_device_token(token: str) -> tuple[str, str] | None:
    """Split a presented bearer token into `(credential_id, secret)`.

    Port of `backend/app/core/security.py::parse_device_token`. Never
    raises; returns `None` for any malformed token (no `.`, or an empty
    credential_id/secret half) so a malformed token is indistinguishable
    from an unknown one at the caller.
    """
    credential_id, sep, secret = token.partition(".")
    if not sep or not credential_id or not secret:
        return None
    return credential_id, secret


def verify_secret(plain_secret: str, secret_hash: str) -> bool:
    """Argon2id-verify `plain_secret` against `secret_hash`.

    Port of `backend/app/core/security.py::verify_secret` (itself an alias
    of `verify_password`). Never raises -- any mismatch or corrupt/foreign
    hash format becomes `False`, so "wrong secret" and "malformed hash" are
    indistinguishable to the caller (NFR-SEC-04).
    """
    try:
        return _hasher.verify(secret_hash, plain_secret)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def get_device_by_credential_id(cursor: Cursor, credential_id: str) -> tuple[str, str, str] | None:
    """`(device_id, credential_hash, status)` for the device whose
    `auth_credential_ref == credential_id`, or `None` if there isn't one.

    `str(...)` on the id column is deliberate, not cosmetic: psycopg returns
    a native `uuid.UUID` for a Postgres `uuid` column (found live during
    TR-08), and callers of this function (and its consumers, e.g. audit
    logging) expect a plain `str` device id throughout, matching
    `ai_inference.gallery.search_top_k`'s identical `str(user_id)` coercion.
    """
    cursor.execute(
        "SELECT id, credential_hash, status FROM devices WHERE auth_credential_ref = %s",
        (credential_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    device_id, credential_hash, status = row
    return str(device_id), str(credential_hash), str(status)


def authenticate_device(cursor: Cursor, token: str) -> str:
    """Resolve+verify a presented bearer token into its owning device id.

    Same order of checks as `backend/app/services/device_service.py::
    authenticate_device`: parse -> lookup -> verify secret -> check
    DISABLED. Raises `InvalidDeviceCredentialError` for any bad-credential
    reason, or `DeviceDisabledError` when the credential is valid but the
    device is administratively `DISABLED`.
    """
    parsed = parse_device_token(token)
    if parsed is None:
        raise InvalidDeviceCredentialError("Malformed device token")
    credential_id, secret = parsed

    row = get_device_by_credential_id(cursor, credential_id)
    if row is None:
        raise InvalidDeviceCredentialError("Unknown device credential")
    device_id, credential_hash, status = row

    if not verify_secret(secret, credential_hash):
        raise InvalidDeviceCredentialError("Invalid device credential")

    if status == "DISABLED":
        raise DeviceDisabledError(device_id)

    return device_id
