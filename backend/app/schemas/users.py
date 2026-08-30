"""Request/response contracts for `{API_V1_PREFIX}/users/*` (BE-04, FR-USR-01)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import UserStatus


class UserCreateRequest(BaseModel):
    external_ref: str = Field(..., min_length=1, max_length=255)
    full_name: str = Field(..., min_length=1, max_length=255)


class UserUpdateRequest(BaseModel):
    """All fields optional — PATCH semantics. Only fields explicitly present
    in the request body are applied (see `exclude_unset` usage in the
    router); a field set to `null` is NOT the same as an omitted field."""

    external_ref: str | None = Field(None, min_length=1, max_length=255)
    full_name: str | None = Field(None, min_length=1, max_length=255)
    status: UserStatus | None = None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    external_ref: str | None
    full_name: str
    status: UserStatus
    created_at: datetime
    updated_at: datetime


class UserListResponse(BaseModel):
    items: list[UserResponse]
    total: int
    limit: int
    offset: int
