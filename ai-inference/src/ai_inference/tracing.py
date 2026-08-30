"""Optional OpenTelemetry tracing hook (XC-04, NFR-OPS-04).

Same pattern as backend/app/core/tracing.py: lazy-imported and a no-op
unless both the ``otel`` extra is installed and an OTLP endpoint is
configured, so the inference service stays runnable in dev/CI without a
collector.

Enable via ``uv sync --extra otel`` + ``OTEL_EXPORTER_OTLP_ENDPOINT``
(e.g. ``http://localhost:4317``).
"""

import logging
import os

from fastapi import FastAPI

logger = logging.getLogger(__name__)


def setup_tracing(app: FastAPI, service_name: str) -> None:
    """Wire up OTel tracing + FastAPI auto-instrumentation, if configured."""
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        logger.debug("OTel tracing disabled (OTEL_EXPORTER_OTLP_ENDPOINT not set)")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning(
            "OTEL_EXPORTER_OTLP_ENDPOINT is set but opentelemetry packages are not "
            "installed; skipping tracing setup (run `uv sync --extra otel`)."
        )
        return

    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
    logger.info(
        "OTel tracing enabled",
        extra={"otlp_endpoint": endpoint, "service_name": service_name},
    )
