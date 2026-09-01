"""Request/response contracts for `{API_V1_PREFIX}/users/*` (BE-04, FR-USR-01)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    # EC-BE-05 (TSD-edge-cases.md A-5): set by the daily re-enrollment-due
    # beat job (age/score criteria) or the EC-TR-03 legacy-backfill job
    # (video past retention). Exposed here so EC-FE-03's badge/UI can
    # actually read it — the column existed on the model before this change
    # but was never surfaced in the API response.
    reenroll_due: bool
    reenroll_due_reason: str | None
    reenroll_due_marked_at: datetime | None

    @field_validator("reenroll_due", mode="before")
    @classmethod
    def _default_reenroll_due_false(cls, value: bool | None) -> bool:
        # The DB column is NOT NULL DEFAULT false, but that default is
        # applied at INSERT/flush time, not on a plain Python `User(...)`
        # object built without touching a real session (several test
        # fixtures across this suite do exactly that). Treat an unset
        # attribute the same as the DB would: False, not a validation error.
        return False if value is None else value


class UserListResponse(BaseModel):
    items: list[UserResponse]
    total: int
    limit: int
    offset: int
