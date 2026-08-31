"""Prometheus metrics for the inference service (IN-05, NFR-PRF-01/02).

Per-stage latency histograms are first-class: every stage of the hot path
gets its own histogram so the p95 <= 300 ms decision budget (NFR-PRF-01)
and the ANN p95 <= 10 ms budget (NFR-PRF-02) can be monitored per stage,
not just inferred from the total `latency_ms` already returned in every
`/recognize` response.

Stage names match TSD SS5's own 5-category latency budget table exactly
(detect <=40ms, liveness <=60ms, embed <=50ms, ANN(search) <=10ms,
overhead <=40ms) rather than inventing extra categories TSD never defined:

- ``detect``: base64 decode + `detect_face_and_landmarks` for one frame.
- ``liveness``: `LivenessDetector.score` for one frame.
- ``embed``: `align_face` + `embedder.embed` for one frame (alignment is
  <1ms per recommendations.md SS6 and is inference-adjacent preprocessing,
  not its own TSD budget line, so it is measured together with embedding
  rather than as a separate stage).
- ``search``: `gallery.search_top_k` (the pgvector ANN query) for one
  frame that reached it.
- ``overhead``: everything else run_recognition does that isn't one of the
  four per-frame stages above (the PRODUCTION-version lookup, the
  `decide_from_scores` voting/decision, Python loop bookkeeping) --
  observed once per request, not once per frame.

The four per-frame stages get ONE observation per frame that reaches that
stage (so many frames across many requests build up a meaningful
percentile distribution); ``overhead`` gets one observation per request.
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
    "Latency per pipeline stage (detect|liveness|embed|search|overhead) -- "
    "detect/liveness/embed/search are observed once per frame, overhead once per request.",
    labelnames=("stage",),
    buckets=_LATENCY_BUCKETS,
    registry=registry,
)

# Separate from stage_latency_seconds: this is the FULL per-request
# latency_ms already returned in every /recognize response (NFR-PRF-01's
# literal "p95 decision <= 300ms" target), not a sum of the per-stage
# histograms above -- percentiles do not add, so a true end-to-end p95
# needs its own histogram rather than being reconstructed from the others.
decision_latency_seconds = Histogram(
    "inference_decision_latency_seconds",
    "Full /recognize request latency (NFR-PRF-01: p95 <= 300ms target), "
    "one observation per request.",
    buckets=_LATENCY_BUCKETS,
    registry=registry,
)

decisions_total = Counter(
    "inference_decisions_total",
    "Access decisions emitted, by outcome (GRANTED|UNKNOWN|SPOOF_SUSPECTED). "
    "DENIED is never produced by ai-inference -- that's a backend/policy concept (BE-10).",
    labelnames=("decision",),
    registry=registry,
)

model_loads_total = Counter(
    "inference_model_loads_total",
    "Model load events, by model kind and result.",
    labelnames=("kind", "result"),
    registry=registry,
)
