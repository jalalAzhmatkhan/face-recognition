"""Request/response schemas for ``POST /recognize`` (IN-03, FR-INF-02).

Base64 JPEG/PNG frames were chosen over multipart (TSD §7 leaves either
option open: "multipart frames | base64 batch") because a JSON body of
base64 strings is simpler to implement AND to test (a plain
``TestClient.post(json=...)`` call, no multipart boundary construction) for
a service that already speaks JSON everywhere else (``/healthz``,
``/metrics``). The tradeoff (≈33% larger payload than raw multipart bytes)
is judged not to matter at this stage; multipart can be added as a second
supported content-type later without breaking this one if it ever does.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RecognizeRequest(BaseModel):
    """One or more frames from a single recognition attempt.

    recommendations.md §5's multi-frame temporal voting (accept if >=2 of
    3-5 frames pass threshold tau) is the reason this is a list rather than
    a single frame -- see ``ai_inference.pipeline.recognize.run_recognition``.
    """

    frames_base64: list[str] = Field(
        min_length=1,
        description="Base64-encoded JPEG or PNG bytes, one entry per captured frame.",
    )


class RecognizeResponse(BaseModel):
    """FR-INF-02 response shape -- field set and names are exact per the
    IN-03 task brief, do not rename without updating callers.

    ``decision`` is intentionally restricted to a SUBSET of backend's full
    ``AccessDecision`` enum (``GRANTED | DENIED | UNKNOWN | SPOOF_SUSPECTED``):
    ``GRANTED``/``UNKNOWN``/``SPOOF_SUSPECTED`` are produced here as of
    IN-04 (see ``ai_inference.pipeline.recognize.decide_from_scores`` for the
    exact voting rule and its ``SPOOF_SUSPECTED`` > ``GRANTED`` > ``UNKNOWN``
    priority). ``DENIED`` still requires a signal this endpoint does not
    produce (an active/interactive liveness check, or a revoked/blocklisted
    identity match) and remains out of scope. See
    ``ai_inference.pipeline.recognize`` module docstring for the full list
    of gaps this endpoint deliberately does not close.
    """

    decision: str  # "GRANTED" | "UNKNOWN" | "SPOOF_SUSPECTED"
    user_id: str | None = None
    similarity: float
    liveness_score: float
    model_version: str
    latency_ms: int
    # EC-IN-02 (TSD-edge-cases.md D-3): additive, optional, backward
    # compatible -- unlike `condition_flags`/`reject_stage` (EC-IN-01,
    # deliberately kept OUT of this client-facing response, see
    # `ai_inference.main`'s `/recognize` handler), this ONE field is meant
    # for the door UI itself: a short operator-facing hint ("mendekatlah")
    # populated whenever the aggregated `condition_flags["low_res"]` was
    # `True` for this decision. `None` (the default) whenever no such
    # guidance applies, which is every response from before this task.
    guidance_message: str | None = None
