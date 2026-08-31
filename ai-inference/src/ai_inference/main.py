"""FastAPI application for the inference service (IN-01 scaffold + IN-03).

Endpoints:
- ``GET /healthz`` - liveness/readiness probe with loaded-model versions.
- ``GET /metrics`` - Prometheus exposition (per-stage latency histograms etc.).
- ``POST /recognize`` - face recognition pipeline (IN-03). See the endpoint
  docstring below for the IN-02/IN-04/IN-06/IN-07 gaps it deliberately does
  NOT close.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from ai_inference import __version__, gallery
from ai_inference.config import Settings, get_settings
from ai_inference.metrics import model_loads_total, registry
from ai_inference.models import ModelKind, build_model_loader
from ai_inference.schemas import RecognizeRequest, RecognizeResponse
from ai_inference.tracing import setup_tracing


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

    @app.post("/recognize", response_model=RecognizeResponse)
    async def recognize(request: RecognizeRequest) -> RecognizeResponse:
        """Face recognition over 1+ base64 frames (IN-03, FR-INF-01/02/03).

        **IN-02 GAP (device auth): this endpoint has NO authentication at
        all.** Any caller that can reach this service can submit frames and
        get a decision back. This MUST be closed (device credential/mTLS/
        whatever IN-02 lands on) before this is exposed to anything but a
        trusted internal network. Not implemented here on purpose -- IN-02
        is a separate, dedicated task.

        See `ai_inference.pipeline.recognize` module docstring for the full
        list of deliberate gaps (IN-04 liveness placeholder, no IN-06 event
        emission, no IN-07 atomic model switch, `SPOOF_SUSPECTED` never
        produced).
        """
        if not settings.db_dsn:
            raise HTTPException(
                status_code=500,
                detail="`/recognize` requires INF_DB_DSN to be configured "
                "(ai_inference_ro role DSN, see backend/README.md).",
            )

        loaded_embedder = loader.load(ModelKind.EMBEDDER)
        embedder = loaded_embedder.handle
        if embedder is None:
            raise HTTPException(
                status_code=500,
                detail="`/recognize` requires a real embedder: set "
                "INF_MODEL_LOADER=adaface (or the legacy 'mlflow' alias) and "
                "install the 'ml' extra.",
            )

        from ai_inference.pipeline.recognize import run_recognition_timed

        try:
            conn = gallery.get_connection(settings.db_dsn)
        except RuntimeError as exc:  # pragma: no cover - depends on extras
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        try:
            with conn.cursor() as cursor:
                response_dict = run_recognition_timed(
                    request.frames_base64, settings, embedder=embedder, cursor=cursor
                )
        finally:
            conn.close()
        return RecognizeResponse(**response_dict)

    # No-op unless OTEL_EXPORTER_OTLP_ENDPOINT is set and the `otel` extra is installed.
    setup_tracing(app, settings.service_name)

    return app


app = create_app()
