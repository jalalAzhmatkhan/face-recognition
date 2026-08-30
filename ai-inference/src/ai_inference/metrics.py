"""Prometheus metrics for the inference service.

Per-stage latency histograms are first-class (NFR-PRF-01/02): every stage of
the hot path (detect / liveness / embed / search / overhead) gets its own
histogram so the p95 <= 300 ms decision budget can be monitored per stage.
"""

from prometheus_client import CollectorRegistry, Counter, Histogram

# Dedicated registry so tests / multiple app instances never collide on the
# global default registry.
registry = CollectorRegistry()

# Latency buckets in seconds, tuned around the ms-level budget of TSD SS5
# (detect <=40ms, liveness <=60ms, embed <=50ms, ANN <=10ms, decision p95 <=300ms).
_LATENCY_BUCKETS = (0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0, 2.5)

stage_latency_seconds = Histogram(
    "inference_stage_latency_seconds",
    "Latency per pipeline stage (detect|align|liveness|embed|search|decision).",
    labelnames=("stage",),
    buckets=_LATENCY_BUCKETS,
    registry=registry,
)

decisions_total = Counter(
    "inference_decisions_total",
    "Access decisions emitted, by outcome (GRANTED|DENIED|UNKNOWN).",
    labelnames=("decision",),
    registry=registry,
)

model_loads_total = Counter(
    "inference_model_loads_total",
    "Model load events, by model kind and result.",
    labelnames=("kind", "result"),
    registry=registry,
)
