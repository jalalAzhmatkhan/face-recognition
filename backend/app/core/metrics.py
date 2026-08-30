"""Prometheus metrics for the Core API (XC-04 observability baseline).

Exposed at ``GET /metrics``. Mirrors the pattern already used in
``ai-inference/src/ai_inference/metrics.py``: a dedicated registry so tests
and multiple app instances never collide on the global default registry.
"""

from prometheus_client import CollectorRegistry, Counter, Histogram

registry = CollectorRegistry()

# Generic HTTP latency buckets in seconds (this is the Core API, not the
# hot inference path — that per-stage ms-level budget lives in
# ai-inference/src/ai_inference/metrics.py per TSD SS5).
_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

http_requests_total = Counter(
    "backend_http_requests_total",
    "Total HTTP requests handled by the Core API, by method/route/status.",
    labelnames=("method", "route", "status"),
    registry=registry,
)

http_request_duration_seconds = Histogram(
    "backend_http_request_duration_seconds",
    "HTTP request latency in seconds, by method/route (NFR-OPS-04).",
    labelnames=("method", "route"),
    buckets=_LATENCY_BUCKETS,
    registry=registry,
)
