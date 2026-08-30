"""AuthN/AuthZ FastAPI dependencies (BE-03, NFR-SEC-04: deny-by-default).

Every business router MUST explicitly depend on `get_current_staff` (or
`require_role(...)`) — there is no global middleware granting access, so an
endpoint that forgets to declare an auth dependency is unauthenticated by
construction. This module is the ONLY place that should decode a staff JWT.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.problem import ProblemError
from app.core.security import TokenError, TokenType, decode_token
from app.db.session import get_db
from app.models.enums import StaffRole
from app.repositories.staff_accounts import StaffAccountRepository

_bearer_scheme = HTTPBearer(auto_error=False)


def get_staff_account_repository(db: Session = Depends(get_db)) -> StaffAccountRepository:
    """Separate dependency (rather than instantiating inline in routers) so
    tests can override just the repository with a fake, without needing a
    real DB session (see backend/tests/test_auth_router.py)."""
    return StaffAccountRepository(db)


@dataclass(frozen=True)
class CurrentStaff:
    id: uuid.UUID
    email: str
    role: StaffRole


def _unauthorized(detail: str) -> ProblemError:
    return ProblemError(status_code=401, title="Unauthorized", detail=detail)


def get_current_staff(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    repo: StaffAccountRepository = Depends(get_staff_account_repository),
) -> CurrentStaff:
    """Resolve+validate the bearer access token into the requesting staff
    account. Raises a 401 problem+json on any missing/invalid/expired token,
    wrong token type, or an account that no longer exists (e.g. offboarded).
    """
    if credentials is None or not credentials.credentials:
        raise _unauthorized("Missing bearer token")

    try:
        payload = decode_token(credentials.credentials, expected_type=TokenType.ACCESS)
    except TokenError as exc:
        raise _unauthorized(str(exc)) from exc

    try:
        staff_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise _unauthorized("Malformed token subject") from exc

    account = repo.get(staff_id)
    if account is None:
        raise _unauthorized("Staff account no longer exists")

    return CurrentStaff(id=account.id, email=account.email, role=account.role)


def require_role(*roles: StaffRole) -> Callable[[CurrentStaff], CurrentStaff]:
    """Dependency factory: `Depends(require_role(StaffRole.ADMIN))`.

    Deny-by-default RBAC — a role not explicitly listed is rejected with 403.
    Always resolves `get_current_staff` first, so an invalid/missing token
    still yields 401 rather than 403.
    """
    allowed = set(roles)

    def _dependency(current: CurrentStaff = Depends(get_current_staff)) -> CurrentStaff:
        if current.role not in allowed:
            raise ProblemError(
                status_code=403,
                title="Forbidden",
                detail=f"Role '{current.role.value}' is not permitted for this operation.",
            )
        return current

    return _dependency
