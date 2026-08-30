"""Request/response contracts for `{API_V1_PREFIX}/enrollments/*` (BE-05,
FR-ENR-01/08)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import EnrollmentState


class EnrollmentCreateRequest(BaseModel):
    user_id: uuid.UUID


class ConsentRequest(BaseModel):
    consent_version: str = Field(..., min_length=1, max_length=50)


class TransitionRequest(BaseModel):
    """Body for `POST /enrollments/{id}/transition`.

    `target_state` is validated twice: once against a small allow-list of
    states this generic endpoint is permitted to reach in BE-05 scope (see
    router docstring), and once against the full state machine
    (`app/services/enrollment_state_machine.py`) for the session's current
    state.
    """

    target_state: EnrollmentState


class EnrollmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    state: EnrollmentState
    qc_report: dict | None
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class EnrollmentListResponse(BaseModel):
    items: list[EnrollmentResponse]
    total: int
    limit: int
    offset: int


class ConsentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    consent_version: str
    granted_at: datetime
    revoked_at: datetime | None
