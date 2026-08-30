"""Device credential AuthN dependency (BE-09, NFR-SEC-04).

Separate from `app/dependencies/auth.py` (which docstrings itself as "the
ONLY place that should decode a staff JWT") because devices are a distinct
principal type with a distinct verification scheme: a bearer token of the
form `<credential_id>.<secret>` looked up by `credential_id` and checked
against an Argon2id hash — never a JWT. See app/services/device_service.py
for issuance/verification and app/core/security.py for the token format.

Every device-facing endpoint (currently only `POST /devices/{id}/heartbeat`)
MUST declare `Depends(get_current_device)` explicitly — same deny-by-default
posture as staff routes.
"""

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.problem import ProblemError
from app.db.session import get_db
from app.models.device import Device
from app.repositories.devices import DeviceRepository
from app.services import device_service

_device_bearer_scheme = HTTPBearer(auto_error=False)


def get_device_repository(db: Session = Depends(get_db)) -> DeviceRepository:
    """Separate dependency (mirrors get_staff_account_repository /
    get_user_repository) so tests can override just the repository with a
    fake, without a real DB session."""
    return DeviceRepository(db)


def _unauthorized(detail: str) -> ProblemError:
    return ProblemError(status_code=401, title="Unauthorized", detail=detail)


def _forbidden(detail: str) -> ProblemError:
    return ProblemError(status_code=403, title="Forbidden", detail=detail)


def get_current_device(
    credentials: HTTPAuthorizationCredentials | None = Depends(_device_bearer_scheme),
    repo: DeviceRepository = Depends(get_device_repository),
) -> Device:
    """Resolve+verify the bearer token into the requesting `Device`.

    401 for anything wrong with the credential itself (missing, malformed,
    unknown, wrong secret — deliberately indistinguishable per
    `InvalidDeviceCredentialError`'s docstring). 403 for a credential that
    checks out but belongs to an administratively DISABLED device — a
    different condition worth signalling differently, mirroring
    `require_role`'s 401-vs-403 split in app/dependencies/auth.py.
    """
    if credentials is None or not credentials.credentials:
        raise _unauthorized("Missing device bearer token")

    try:
        device = device_service.authenticate_device(repo, token=credentials.credentials)
    except device_service.InvalidDeviceCredentialError as exc:
        raise _unauthorized(str(exc)) from exc
    except device_service.DeviceDisabledError as exc:
        raise _forbidden(f"Device '{exc.device.id}' is disabled") from exc

    return device
