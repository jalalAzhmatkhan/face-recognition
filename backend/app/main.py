"""Application factory for the Core API.

Layering: routers (HTTP) -> services (business logic) -> repositories (data access).
All future business routers mount under `settings.api_v1_prefix` and MUST declare
auth dependencies (deny-by-default, NFR-SEC-04) — added in task BE-03.
"""

import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.core.metrics import http_request_duration_seconds, http_requests_total
from app.core.problem import register_exception_handlers
from app.core.tracing import setup_tracing
from app.routers import (
    access_events,
    access_policies,
    auth,
    devices,
    enrollments,
    health,
    observability,
    training,
    users,
)


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Core API — Face Recognition Access Control",
    )
    register_exception_handlers(app)

    # Deny-by-default: only add CORS middleware when origins are explicitly
    # configured (never a permissive "*" fallback). Credentials are allowed
    # since the frontend sends the bearer token, not cookies, but keeping
    # allow_credentials scoped to an explicit origin list (never "*") avoids
    # the browser-rejected "wildcard + credentials" combination.
    if settings.cors_allow_origins_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allow_origins_list,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def record_request_metrics(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start

        # Prefer the matched route's path template (e.g. "/users/{id}") over
        # the raw URL so metric label cardinality stays bounded; fall back to
        # the raw path for unmatched routes (404s).
        route = request.scope.get("route")
        route_path = route.path if route is not None else request.url.path

        http_requests_total.labels(
            method=request.method, route=route_path, status=str(response.status_code)
        ).inc()
        http_request_duration_seconds.labels(method=request.method, route=route_path).observe(
            duration
        )
        return response

    # Health & observability endpoints stay outside the versioned/authenticated prefix.
    app.include_router(health.router)
    app.include_router(observability.router)

    # Versioned/authenticated business API (BE-03+). auth.router itself hosts
    # the only unauthenticated endpoints under this prefix (login/refresh);
    # every other router mounted here must declare its own auth dependency.
    app.include_router(auth.router, prefix=settings.api_v1_prefix)
    app.include_router(users.router, prefix=settings.api_v1_prefix)
    app.include_router(enrollments.router, prefix=settings.api_v1_prefix)
    app.include_router(devices.router, prefix=settings.api_v1_prefix)
    app.include_router(access_policies.router, prefix=settings.api_v1_prefix)
    app.include_router(access_events.router, prefix=settings.api_v1_prefix)
    app.include_router(training.router, prefix=settings.api_v1_prefix)

    # No-op unless OTEL_EXPORTER_OTLP_ENDPOINT is set and the `otel` extra is installed.
    setup_tracing(app, settings.app_name)

    return app


app = create_app()
