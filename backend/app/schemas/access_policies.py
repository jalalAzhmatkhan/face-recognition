"""Request/response contracts for `{API_V1_PREFIX}/access-policies/*` (BE-10)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AccessPolicyCreateRequest(BaseModel):
    user_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    door_group: str = Field(..., min_length=1, max_length=255)
    allowed: bool = True
    valid_from: datetime | None = None
    valid_to: datetime | None = None

    @model_validator(mode="after")
    def _require_user_or_group(self) -> "AccessPolicyCreateRequest":
        if self.user_id is None and self.group_id is None:
            raise ValueError("At least one of user_id or group_id must be provided.")
        return self


class AccessPolicyUpdateRequest(BaseModel):
    """PATCH semantics: only `allowed`/`valid_from`/`valid_to` are mutable
    per BE-10 task instructions — `user_id`/`group_id`/`door_group` are
    fixed at creation (changing "who/what this policy is for" is modeled as
    delete + recreate, not an update)."""

    allowed: bool | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class AccessPolicyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID | None
    group_id: uuid.UUID | None
    door_group: str
    allowed: bool
    valid_from: datetime | None
    valid_to: datetime | None


class AccessPolicyListResponse(BaseModel):
    items: list[AccessPolicyResponse]
    total: int
    limit: int
    offset: int
