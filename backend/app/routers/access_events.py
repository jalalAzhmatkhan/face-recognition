"""Access events ingest + monitoring API (BE-10, TSD §2.2/§4/§7,
FR-INF-01..06, FR-MON-01).

`POST /access-events` is device-authenticated (`get_current_device`, BE-09)
rather than staff JWT — it is the contract `ai-inference` (IN-03, not yet
built) will call to report a recognition decision for its own door. Exactly
like `POST /devices/{id}/heartbeat`, `device_id` is taken from the verified
token, NEVER from the request body, so a device can never fabricate an event
for a different device's door (see app/dependencies/device_auth.py).

`GET /access-events` is staff-read (ADMIN/OPERATOR/VIEWER) — this is
monitoring/audit data (FR-MON-01), not a sensitive administrative action, so
VIEWER is included here unlike the stricter device-registry endpoints.

`GET /stream/access-events` (SSE, BE-11) shares the same staff-read RBAC as
`GET /access-events` and reuses `AccessEventResponse`'s JSON shape for the
stream payload (see `access_event_service._publish_access_event`). Its
generator logic lives in `app/services/access_event_stream.py` rather than
inline here, so it can be unit tested directly against a fake async Redis
client (see that module's docstring for why).
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.redis_client import get_async_redis_client, get_redis_client
from app.db.session import get_db
from app.dependencies.auth import CurrentStaff, require_role
from app.dependencies.device_auth import get_current_device
from app.models.device import Device
from app.models.enums import AccessDecision, StaffRole
from app.repositories.access_events import AccessEventRepository
from app.repositories.access_policies import AccessPolicyRepository
from app.repositories.users import UserRepository
from app.schemas.access_events import (
    AccessEventIngestRequest,
    AccessEventIngestResponse,
    AccessEventListResponse,
    AccessEventResponse,
)
from app.services import access_event_service
from app.services.access_event_stream import stream_access_events

router = APIRouter(tags=["access-events"])

READ_ROLES = (StaffRole.ADMIN, StaffRole.OPERATOR, StaffRole.VIEWER)


def get_access_event_repository(db: Session = Depends(get_db)) -> AccessEventRepository:
    """Separate dependency (mirrors get_device_repository) so tests can
    override just the repository with an in-memory fake, without a real DB
    session (see backend/tests/test_access_events_router.py)."""
    return AccessEventRepository(db)


def get_access_policy_repository(db: Session = Depends(get_db)) -> AccessPolicyRepository:
    return AccessPolicyRepository(db)


def get_user_repository(db: Session = Depends(get_db)) -> UserRepository:
    return UserRepository(db)


@router.post("/access-events", response_model=AccessEventIngestResponse, status_code=201)
def ingest_access_event(
    body: AccessEventIngestRequest,
    current_device: Device = Depends(get_current_device),
    event_repo: AccessEventRepository = Depends(get_access_event_repository),
    user_repo: UserRepository = Depends(get_user_repository),
    policy_repo: AccessPolicyRepository = Depends(get_access_policy_repository),
    redis_client=Depends(get_redis_client),
) -> AccessEventIngestResponse:
    event = access_event_service.ingest_access_event(
        event_repo,
        user_repo,
        policy_repo,
        redis_client,
        device=current_device,
        decision=body.decision,
        matched_user_id=body.matched_user_id,
        similarity=body.similarity,
        liveness_score=body.liveness_score,
        model_version=body.model_version,
        latency_ms=body.latency_ms,
        frame_media_id=body.frame_media_id,
    )
    return AccessEventIngestResponse(
        id=event.id,
        decision=event.decision,
        door_command_issued=event.door_command_issued,
        occurred_at=event.occurred_at,
    )


@router.get("/access-events", response_model=AccessEventListResponse)
def list_access_events(
    device_id: uuid.UUID | None = Query(None),
    decision: AccessDecision | None = Query(None),
    occurred_from: datetime | None = Query(None, alias="from"),
    occurred_to: datetime | None = Query(None, alias="to"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current: CurrentStaff = Depends(require_role(*READ_ROLES)),
    repo: AccessEventRepository = Depends(get_access_event_repository),
) -> AccessEventListResponse:
    items, total = access_event_service.list_access_events(
        repo,
        device_id=device_id,
        decision=decision,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
        limit=limit,
        offset=offset,
    )
    return AccessEventListResponse(
        items=[AccessEventResponse.model_validate(e) for e in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/stream/access-events")
def stream_access_events_endpoint(
    request: Request,
    device_id: uuid.UUID | None = Query(None),
    decision: AccessDecision | None = Query(None),
    current: CurrentStaff = Depends(require_role(*READ_ROLES)),
    async_redis_client=Depends(get_async_redis_client),
) -> StreamingResponse:
    """SSE live feed of access events (BE-11, FR-MON-01), same RBAC and
    filters as `GET /access-events`. See `app/services/access_event_stream.py`
    for the generator itself."""
    generator = stream_access_events(
        async_redis_client, request, device_id=device_id, decision=decision
    )
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Prevents an intermediate Nginx proxy from buffering the SSE
            # stream, which would defeat the point of "live".
            "X-Accel-Buffering": "no",
        },
    )
