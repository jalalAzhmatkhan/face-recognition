"""FastAPI dependency wiring for device AuthN (IN-02, NFR-SEC-04).

Separate module from `ai_inference.device_auth` (pure logic, DB/HTTP-agnostic,
unit-testable with a fake cursor) so this thin FastAPI-specific layer --
bearer-token extraction, opening/closing the `ai_inference_ro` DB connection,
and mapping exceptions to HTTP status codes -- can be swapped out via
`app.dependency_overrides` in tests without needing a real Postgres
connection. Mirrors `backend/app/dependencies/device_auth.py`'s shape
(`HTTPBearer(auto_error=False)`, 401 for any credential problem, 403 only for
a DISABLED device) even though the underlying verification code is this
service's own (`ai_inference.device_auth`), not backend's -- see that
module's docstring for why the logic itself isn't imported/shared.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ai_inference import device_auth, gallery
from ai_inference.config import Settings

_device_bearer_scheme = HTTPBearer(auto_error=False)


def get_settings_from_state(request: Request) -> Settings:
    """Reads `app.state.settings` (set in `create_app`) rather than calling
    `get_settings()` directly, so a `TestClient` built against an app with
    custom `Settings` (e.g. a test DSN) is respected here too."""
    return request.app.state.settings


async def get_current_device_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(_device_bearer_scheme),
    settings: Settings = Depends(get_settings_from_state),
) -> str:
    """Resolve+verify the bearer token into the requesting device's id.

    401 for anything wrong with the credential itself (missing, malformed,
    unknown, wrong secret -- deliberately indistinguishable, per
    `InvalidDeviceCredentialError`'s docstring). 403 for a credential that
    checks out but belongs to an administratively DISABLED device.

    Declared as a plain `Depends()`-injected function (not called directly
    anywhere) specifically so tests can replace it wholesale via
    `app.dependency_overrides[get_current_device_id] = ...` without needing
    a database at all -- see `tests/test_recognize_auth.py`.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Missing device bearer token")

    # Fail fast on a structurally malformed token WITHOUT opening a DB
    # connection -- avoids an unnecessary round trip (and, in envs without
    # the `ml` extra's psycopg installed, an unrelated ImportError) for
    # garbage input that could never authenticate anyway. Still routed
    # through the same `InvalidDeviceCredentialError` -> 401 mapping as
    # every other credential failure, so the response is identical either
    # way (NFR-SEC-04: no distinguishing signal).
    if device_auth.parse_device_token(credentials.credentials) is None:
        raise HTTPException(status_code=401, detail="Malformed device token")

    conn = gallery.get_connection(settings.db_dsn)
    try:
        with conn.cursor() as cursor:
            try:
                return device_auth.authenticate_device(cursor, credentials.credentials)
            except device_auth.InvalidDeviceCredentialError as exc:
                raise HTTPException(status_code=401, detail=str(exc)) from exc
            except device_auth.DeviceDisabledError as exc:
                raise HTTPException(
                    status_code=403, detail=f"Device '{exc.device_id}' is disabled"
                ) from exc
    finally:
        conn.close()


async def get_current_device_bearer_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_device_bearer_scheme),
) -> str | None:
    """Raw bearer token string (`<credential_id>.<secret>`), for call sites
    that need to FORWARD the same credential elsewhere rather than resolve
    it to a device id (IN-06: `POST /access-events` is device-authenticated
    by backend too, with no separate service-to-service auth path, so
    ai-inference must re-present the same token the caller used for
    `/recognize`). Does not re-verify anything -- `get_current_device_id` is
    what actually authenticates the request; this just exposes the raw
    string already extracted by the same `HTTPBearer` scheme. Returns `None`
    only if no bearer token was supplied at all, which never happens on a
    request that also passed `get_current_device_id`."""
    return credentials.credentials if credentials else None
