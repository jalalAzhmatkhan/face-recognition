"""Request/response contracts for `POST /api/v1/auth/*` (BE-03)."""

import uuid

from pydantic import BaseModel, EmailStr

from app.models.enums import StaffRole


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


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
