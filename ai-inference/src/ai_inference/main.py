"""FastAPI application for the inference service (IN-01 scaffold + IN-03).

Endpoints:
- ``GET /healthz`` - liveness/readiness probe with loaded-model versions.
- ``GET /metrics`` - Prometheus exposition (per-stage latency histograms etc.).
- ``POST /recognize`` - face recognition pipeline (IN-03, liveness/PAD added
  IN-04). See the endpoint docstring below for the IN-02/IN-06/IN-07 gaps it
  deliberately does NOT close.
"""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from ai_inference import __version__, gallery
from ai_inference.auth_dependency import get_current_device_id
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
    async def recognize(
        request: RecognizeRequest,
        device_id: str = Depends(get_current_device_id),
    ) -> RecognizeResponse:
        """Face recognition over 1+ base64 frames (IN-03, FR-INF-01/02/03).

        **IN-02 (device auth)**: requires a valid device bearer token
        (`<credential_id>.<secret>`), verified against the `devices` table
        via the `ai_inference_ro` role -- see `ai_inference.device_auth` and
        `ai_inference.auth_dependency.get_current_device_id`. Missing/
        malformed/unknown/wrong-secret credentials -> 401; a credential
        belonging to an administratively DISABLED device -> 403
        (NFR-SEC-04). `device_id` is resolved but not yet used to scope the
        gallery search or attributed to an `access_events` row -- that lands
        with IN-06 (event emission).

        See `ai_inference.pipeline.recognize` module docstring for the full
        list of other deliberate gaps (no IN-06 event emission, no IN-07
        atomic model switch). IN-04 (real liveness/PAD, `SPOOF_SUSPECTED`)
        is now closed -- see that module for the MiniFASNet-based gate.
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

        # IN-04: liveness gate runs on the same real-backend requirement as
        # the embedder above -- fail closed (500), never silently skip the
        # spoof check, per NFR-SEC-06.
        loaded_liveness = loader.load(ModelKind.LIVENESS)
        liveness_detector = loaded_liveness.handle
        if liveness_detector is None:
            raise HTTPException(
                status_code=500,
                detail="`/recognize` requires a real liveness detector: set "
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
                    request.frames_base64,
                    settings,
                    embedder=embedder,
                    cursor=cursor,
                    liveness_detector=liveness_detector,
                )
        finally:
            conn.close()
        return RecognizeResponse(**response_dict)

    # No-op unless OTEL_EXPORTER_OTLP_ENDPOINT is set and the `otel` extra is installed.
    setup_tracing(app, settings.service_name)

    return app


app = create_app()
