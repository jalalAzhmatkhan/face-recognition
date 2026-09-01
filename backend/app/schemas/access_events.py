"""Request/response contracts for `{API_V1_PREFIX}/access-events/*` (BE-10,
FR-INF-01..06, FR-MON-01).

`GET /stream/access-events` (SSE) is a separate task (BE-11) and has no
schema here — these contracts only need to stay shaped so BE-11 can reuse
`AccessEventResponse` for its stream payload later.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AccessDecision, DeviceClass, RejectStage


class AccessEventIngestRequest(BaseModel):
    """Reported by the device/inference caller (device-credential
    authenticated — see app/dependencies/device_auth.py). `device_id` is
    deliberately NOT a field here: it is taken from the authenticated
    device's token, never trusted from the body (anti-spoofing, mirrors
    the heartbeat endpoint's path-id-vs-token-owner check). `device_class`
    is likewise NOT a field here — it is denormalized server-side from the
    authenticated device's own `device_class` (EC-BE-01, TSD-edge-cases.md
    D-1), never accepted from the caller.

    `condition_flags` and `reject_stage` are EC-BE-01 additions
    (TSD-edge-cases.md D-1, funnel logging) — both optional so a caller
    that predates them (or an older `ai-inference` build) keeps working
    unchanged."""

    decision: AccessDecision
    matched_user_id: uuid.UUID | None = None
    similarity: float | None = Field(None, ge=0.0, le=1.0)
    liveness_score: float | None = Field(None, ge=0.0, le=1.0)
    model_version: str | None = None
    latency_ms: int | None = Field(None, ge=0)
    frame_media_id: uuid.UUID | None = None
    # Canonical keys (TSD-edge-cases.md D-1/D-3): `masked`, `dark`,
    # `blurry`, `low_res`, `sunglasses` (booleans). Left as a loose
    # dict — not a fixed sub-model — so ai-inference can add a new
    # condition flag without a backend schema change; the DB column is
    # jsonb for the same reason (see app/models/access_event.py).
    condition_flags: dict[str, bool] | None = None
    reject_stage: RejectStage | None = None


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
    condition_flags: dict[str, bool] | None = None
    reject_stage: RejectStage | None = None
    device_class: DeviceClass | None = None


class AccessEventListResponse(BaseModel):
    items: list[AccessEventResponse]
    total: int
    limit: int
    offset: int
