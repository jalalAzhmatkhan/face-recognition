"""Staff AuthN/AuthZ endpoints (BE-03, FR-USR-02, NFR-SEC-04).

`login`/`refresh` are the only unauthenticated endpoints in this router by
necessity (you need a token to get a token); every other endpoint here (and
every future business router) MUST declare an explicit auth dependency —
`GET /me` demonstrates the pattern, and `GET /admin-only-example` demonstrates
`require_role` for RBAC.
"""

from fastapi import APIRouter, Depends

from app.core.problem import ProblemError
from app.dependencies.auth import (
    CurrentStaff,
    get_current_staff,
    get_staff_account_repository,
    require_role,
)
from app.models.enums import StaffRole
from app.repositories.staff_accounts import StaffAccountRepository
from app.schemas.auth import (
    AccessTokenResponse,
    BootstrapAdminRequest,
    LoginRequest,
    MeResponse,
    RefreshRequest,
    SetupStatusResponse,
    TokenResponse,
)
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(
    body: LoginRequest,
    repo: StaffAccountRepository = Depends(get_staff_account_repository),
) -> TokenResponse:
    try:
        account = auth_service.authenticate(repo, email=body.email, password=body.password)
    except auth_service.InvalidCredentialsError as exc:
        # Generic on purpose (NFR-SEC-04): identical response whether the
        # email doesn't exist or the password is wrong.
        raise ProblemError(
            status_code=401, title="Unauthorized", detail="Invalid email or password."
        ) from exc

    access_token, refresh_token, expires_in = auth_service.issue_tokens(account)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
    )


@router.post("/refresh", response_model=AccessTokenResponse)
def refresh(
    body: RefreshRequest,
    repo: StaffAccountRepository = Depends(get_staff_account_repository),
) -> AccessTokenResponse:
    try:
        access_token, expires_in = auth_service.refresh_access_token(
            repo, refresh_token=body.refresh_token
        )
    except auth_service.InvalidRefreshTokenError as exc:
        raise ProblemError(
            status_code=401, title="Unauthorized", detail="Invalid or expired refresh token."
        ) from exc

    return AccessTokenResponse(access_token=access_token, expires_in=expires_in)


@router.get("/setup-status", response_model=SetupStatusResponse)
def setup_status(
    repo: StaffAccountRepository = Depends(get_staff_account_repository),
) -> SetupStatusResponse:
    """Unauthenticated on purpose -- the frontend needs this before any staff
    account (and therefore any token) exists, to decide whether to show the
    first-run "create ADMIN account" screen at all."""
    return SetupStatusResponse(needs_setup=auth_service.needs_admin_bootstrap(repo))


@router.post("/bootstrap-admin", response_model=TokenResponse)
def bootstrap_admin(
    body: BootstrapAdminRequest,
    repo: StaffAccountRepository = Depends(get_staff_account_repository),
) -> TokenResponse:
    """Unauthenticated on purpose (same reasoning as `setup_status`) but
    self-disabling: fails with 409 the moment any ADMIN account exists, so
    it can never be used to create a second one from the outside."""
    try:
        account = auth_service.bootstrap_admin(repo, email=body.email, password=body.password)
    except auth_service.AdminAlreadyExistsError as exc:
        raise ProblemError(
            status_code=409,
            title="Conflict",
            detail="An ADMIN account already exists; bootstrap is only available once.",
        ) from exc

    access_token, refresh_token, expires_in = auth_service.issue_tokens(account)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
    )


@router.get("/me", response_model=MeResponse)
def me(current: CurrentStaff = Depends(get_current_staff)) -> MeResponse:
    """Example of a protected endpoint: any valid staff token, any role."""
    return MeResponse(id=current.id, email=current.email, role=current.role)


@router.get("/admin-only-example", response_model=MeResponse)
def admin_only_example(
    current: CurrentStaff = Depends(require_role(StaffRole.ADMIN)),
) -> MeResponse:
    """Demonstrates `require_role` RBAC — ADMIN only, everyone else gets 403.

    Not a real business endpoint; exists to prove the deny-by-default RBAC
    pattern other routers should copy.
    """
    return MeResponse(id=current.id, email=current.email, role=current.role)
