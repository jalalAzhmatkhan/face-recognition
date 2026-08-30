"""Application factory for the Core API.

Layering: routers (HTTP) -> services (business logic) -> repositories (data access).
All future business routers mount under `settings.api_v1_prefix` and MUST declare
auth dependencies (deny-by-default, NFR-SEC-04) — added in task BE-03.
"""

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.core.problem import register_exception_handlers
from app.routers import health


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Core API — Face Recognition Access Control",
    )
    register_exception_handlers(app)

    # Health endpoints stay outside the versioned/authenticated prefix.
    app.include_router(health.router)

    return app


app = create_app()
