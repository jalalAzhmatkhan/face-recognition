"""Health endpoints (unauthenticated by design — used by orchestrators/CI).

`/healthz` is LIVENESS: is the process up. It must not touch the database,
because a database blip should not get the container restarted.

`/readyz` is READINESS: should this instance be serving traffic. It checks
the one thing that silently breaks requests across the whole API — a
database whose schema is behind the code's migration head. See
`app/services/schema_check.py` for why that check earns its keep.
"""

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import get_engine
from app.services import schema_check

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    service: str
    env: str


class ReadinessResponse(BaseModel):
    status: str
    database: str
    schema_in_sync: bool
    schema_applied_revision: str | None
    schema_expected_revision: str | None
    detail: str


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(status="ok", service=settings.app_name, env=settings.app_env)


@router.get("/readyz", response_model=ReadinessResponse)
def readyz(response: Response) -> ReadinessResponse:
    """503 when the database is unreachable or its schema is behind the
    code. The body says which revision is applied, which is expected, and
    the command to fix it — the information that was missing when a pending
    migration presented as an unexplained 500 on an unrelated endpoint."""
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
            result = schema_check.check_schema(connection)
    except Exception as exc:  # noqa: BLE001 - a probe reports, it does not raise
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(
            status="unavailable",
            database="unreachable",
            schema_in_sync=False,
            schema_applied_revision=None,
            schema_expected_revision=schema_check.expected_head(),
            detail=f"Database is not reachable: {type(exc).__name__}",
        )

    if not result.in_sync:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ok" if result.in_sync else "degraded",
        database="reachable",
        schema_in_sync=result.in_sync,
        schema_applied_revision=result.applied,
        schema_expected_revision=result.expected,
        detail=result.detail,
    )
