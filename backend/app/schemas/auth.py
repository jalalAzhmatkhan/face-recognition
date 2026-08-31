"""Request/response contracts for `POST /api/v1/auth/*` (BE-03)."""

import uuid

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import StaffRole


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class SetupStatusResponse(BaseModel):
    """`GET /auth/setup-status` — tells the frontend whether the first-run
    "create ADMIN account" screen should be shown at all (`needs_setup=True`
    only while zero ADMIN accounts exist anywhere)."""

    needs_setup: bool


class BootstrapAdminRequest(BaseModel):
    """`POST /auth/bootstrap-admin` — only succeeds once, while
    `needs_setup` is still true (see `app.services.auth_service.bootstrap_admin`)."""

    email: EmailStr
    password: str = Field(min_length=8)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    """Deliberately the SAME message regardless of whether `email` matched
    an account (NFR-SEC-04) — see `auth_service.request_password_reset`."""

    message: str = "Jika email terdaftar, tautan reset password telah dikirim."


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8)


class ResetPasswordResponse(BaseModel):
    message: str = "Password berhasil direset. Silakan login dengan password baru."


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class AccessTokenResponse(BaseModel):
    """`/auth/refresh` only rotates the access token (see README for the
    minimal-rotation rationale)."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str
    role: StaffRole
