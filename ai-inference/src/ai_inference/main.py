"""FastAPI application for the inference service (IN-01 scaffold).

Endpoints:
- ``GET /healthz`` - liveness/readiness probe with loaded-model versions.
- ``GET /metrics`` - Prometheus exposition (per-stage latency histograms etc.).

``/recognize`` (the hot path) lands with IN-03.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from ai_inference import __version__
from ai_inference.config import Settings, get_settings
from ai_inference.metrics import model_loads_total, registry
from ai_inference.models import ModelKind, build_model_loader


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    loader = build_model_loader(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Warm-load pipeline models at startup (stub backend is instant).
        for kind in ModelKind:
            loader.load(kind)
            model_loads_total.labels(kind=kind.value, result="ok").inc()
        yield

    app = FastAPI(title=settings.service_name, version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.model_loader = loader

    @app.get("/healthz")
    async def healthz() -> dict:
        return {
            "status": "ok",
            "service": settings.service_name,
            "version": __version__,
            "model_loader": settings.model_loader,
            "models": {k.value: v for k, v in loader.loaded_versions().items()},
        }

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(content=generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
