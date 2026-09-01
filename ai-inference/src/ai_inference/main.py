"""FastAPI application for the inference service (IN-01 scaffold + IN-03).

Endpoints:
- ``GET /healthz`` - liveness/readiness probe with loaded-model versions.
- ``GET /metrics`` - Prometheus exposition (per-stage latency histograms etc.).
- ``POST /recognize`` - face recognition pipeline (IN-03, liveness/PAD added
  IN-04, access-event emission added IN-06, atomic model+gallery switch
  guard added IN-07). See the endpoint docstring below for details.
"""

import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from ai_inference import __version__, events, gallery, monitoring
from ai_inference.auth_dependency import get_current_device_bearer_token, get_current_device_id
from ai_inference.config import Settings, get_settings
from ai_inference.metrics import model_loads_total, registry
from ai_inference.model_switch import ProductionVersionCache
from ai_inference.models import ModelKind, build_model_loader
from ai_inference.schemas import RecognizeRequest, RecognizeResponse
from ai_inference.tracing import setup_tracing


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    loader = build_model_loader(settings)
    # IN-07: one cache per app instance (not module-global, unlike IN-06's
    # event buffer) -- each `create_app()` call (e.g. one per test) gets an
    # independent, un-warmed cache, matching how `loader` itself is scoped.
    production_version_cache = ProductionVersionCache(settings.production_version_cache_ttl_seconds)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Warm-load pipeline models at startup (stub backend is instant).
        for kind in ModelKind:
            loader.load(kind)
            model_loads_total.labels(kind=kind.value, result="ok").inc()

        # IN-06: periodic retry of the in-memory access-event fallback
        # buffer, for the lifetime of the app (cancelled at shutdown below).
        events.configure_buffer(settings.access_event_buffer_max_size)
        flush_task = asyncio.create_task(events.run_flush_loop(settings))

        # IN-08: fresh drift/unknown-rate/latency-SLO detectors for this
        # process's lifetime (module-global by design, see
        # ai_inference.monitoring module docstring).
        monitoring.configure(settings)
        try:
            yield
        finally:
            flush_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await flush_task

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
        background_tasks: BackgroundTasks,
        device_id: str = Depends(get_current_device_id),
        device_bearer_token: str | None = Depends(get_current_device_bearer_token),
    ) -> RecognizeResponse:
        """Face recognition over 1+ base64 frames (IN-03, FR-INF-01/02/03).

        **IN-02 (device auth)**: requires a valid device bearer token
        (`<credential_id>.<secret>`), verified against the `devices` table
        via the `ai_inference_ro` role -- see `ai_inference.device_auth` and
        `ai_inference.auth_dependency.get_current_device_id`. Missing/
        malformed/unknown/wrong-secret credentials -> 401; a credential
        belonging to an administratively DISABLED device -> 403
        (NFR-SEC-04). `device_id` is resolved but not yet used to scope the
        gallery search.

        **IN-06 (access-event emission)**: after computing the decision, the
        SAME device bearer token is forwarded to backend's own
        `POST /access-events` (BE-10) via `BackgroundTasks` -- fire-and-forget,
        after this response is already returned, per TSD SS1.3/NFR-PRF-01. A
        failed/slow backend never delays or fails this response; see
        `ai_inference.events` module docstring for the fallback-buffer
        mechanism.

        **EC-IN-01 (funnel logging, TSD-edge-cases.md D-1)**: that same
        access-event payload is additionally enriched with `condition_flags`
        (dark/blurry/low_res/masked/sunglasses -- see
        `ai_inference.pipeline.condition_flags`) and `reject_stage`
        (`ai_inference.pipeline.recognize._determine_reject_stage`), both
        computed inside `run_recognition`/`run_recognition_timed` with
        negligible (<1ms/frame) overhead and popped out of `response_dict`
        below so they never leak into the client-facing `RecognizeResponse`.

        **IN-07 (atomic model+gallery switch)**: the current PRODUCTION
        `models.version` is read through a short-TTL cache
        (`app.state`-scoped `ai_inference.model_switch.ProductionVersionCache`,
        see `create_app`) rather than fresh every call, and this process's
        loaded embedder version is checked against it before any gallery
        search -- a mismatch fail-secures the whole request to `UNKNOWN`.
        See `ai_inference.model_switch` module docstring for why this is a
        fail-secure guard, not a live weight hot-swap.

        IN-04 (real liveness/PAD, `SPOOF_SUSPECTED`) is closed -- see
        `ai_inference.pipeline.recognize` for the MiniFASNet-based gate.
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
                    production_version_cache=production_version_cache,
                )
        finally:
            conn.close()

        # EC-IN-01 (TSD-edge-cases.md D-1): pop the two funnel-logging keys
        # BEFORE constructing `RecognizeResponse` below -- they are additive
        # to the `POST /access-events` payload only, never part of the
        # client-facing `/recognize` response contract (see
        # `run_recognition_timed`'s docstring for why they're returned in
        # this same dict in the first place).
        condition_flags = response_dict.pop("condition_flags")
        reject_stage = response_dict.pop("reject_stage")

        if device_bearer_token is not None:
            background_tasks.add_task(
                events.emit_access_event_background,
                settings,
                device_bearer_token,
                {
                    "decision": response_dict["decision"],
                    "matched_user_id": response_dict["user_id"],
                    "similarity": response_dict["similarity"],
                    "liveness_score": response_dict["liveness_score"],
                    "model_version": response_dict["model_version"] or None,
                    "latency_ms": response_dict["latency_ms"],
                    # EC-IN-01 additions (backend/app/schemas/access_events.py
                    # AccessEventIngestRequest.condition_flags/reject_stage):
                    # both optional server-side, sent whenever this
                    # ai-inference build computes them.
                    "condition_flags": condition_flags,
                    "reject_stage": reject_stage,
                },
            )
        return RecognizeResponse(**response_dict)

    # No-op unless OTEL_EXPORTER_OTLP_ENDPOINT is set and the `otel` extra is installed.
    setup_tracing(app, settings.service_name)

    return app


app = create_app()
