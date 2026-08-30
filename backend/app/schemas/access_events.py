"""Request/response contracts for `{API_V1_PREFIX}/access-events/*` (BE-10,
FR-INF-01..06, FR-MON-01).

`GET /stream/access-events` (SSE) is a separate task (BE-11) and has no
schema here — these contracts only need to stay shaped so BE-11 can reuse
`AccessEventResponse` for its stream payload later.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AccessDecision


class AccessEventIngestRequest(BaseModel):
    """Reported by the device/inference caller (device-credential
    authenticated — see app/dependencies/device_auth.py). `device_id` is
    deliberately NOT a field here: it is taken from the authenticated
    device's token, never trusted from the body (anti-spoofing, mirrors
    the heartbeat endpoint's path-id-vs-token-owner check)."""

    decision: AccessDecision
    matched_user_id: uuid.UUID | None = None
    similarity: float | None = Field(None, ge=0.0, le=1.0)
    liveness_score: float | None = Field(None, ge=0.0, le=1.0)
    model_version: str | None = None
    latency_ms: int | None = Field(None, ge=0)
    frame_media_id: uuid.UUID | None = None


class AccessEventIngestResponse(BaseModel):
    id: uuid.UUID
    decision: AccessDecision
    door_command_issued: bool
    occurred_at: datetime


class AccessEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    occurred_at: datetime
    device_id: uuid.UUID
    decision: AccessDecision
    matched_user_id: uuid.UUID | None
    similarity: float | None
    liveness_score: float | None
    model_version: str | None
    latency_ms: int | None
    frame_media_id: uuid.UUID | None
    door_command_issued: bool


class AccessEventListResponse(BaseModel):
    items: list[AccessEventResponse]
    total: int
    limit: int
    offset: int
