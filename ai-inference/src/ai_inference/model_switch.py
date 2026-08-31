"""IN-07: atomic `{model_version, gallery_version}` switch (TSD, FR-TRN-06:
"rollout is atomic per model version (no mixed-version matching)").

Two separate concerns, addressed separately below:

1. **Performance** -- `gallery.get_current_production_model_version` hits
   Postgres on every single `/recognize` call (flagged as IN-07's literal
   gap in `ai_inference.pipeline.recognize`'s pre-IN-07 module docstring).
   `ProductionVersionCache` adds a short-TTL cache in front of it, mirroring
   backend's own cached-policy-snapshot pattern
   (`app/services/access_event_service.py`, TTL <= 30s, fail-secure on
   miss): a cache miss/expiry just re-queries -- it never blocks, retries,
   or fails a request, it only bounds how often Postgres is hit.

2. **Correctness -- the actual FR-TRN-06 guarantee**: this service's loaded
   EMBEDDER is a process-lifetime singleton built once from static config
   (see `ai_inference.models.loader` module docstring: `AdaFaceModelLoader`
   never reloads a different checkpoint after startup). There is no dynamic
   per-model-version weight-loading registry anywhere in this codebase yet
   (`ai_training.worker.tasks.run_gallery_reembed_job`'s own docstring calls
   this out explicitly) -- promoting a NEW model version in backend does
   NOT make this process's embedder reload to match it. If this process's
   loaded embedder version ever diverges from the current PRODUCTION
   `models.version`, computing a query embedding with the OLD model and
   comparing it against a gallery re-embedded (TR-08) under the NEW
   `model_version` would silently mix two incompatible embedding spaces --
   exactly what FR-TRN-06 prohibits. `embedder_matches_production` makes
   that divergence a hard, observable, fail-secure stop (treated exactly
   like "no PRODUCTION model" -- return `UNKNOWN`, never attempt the
   comparison) instead of a silent wrong-but-plausible similarity score.

   This does NOT require hot-swapping model weights to be correct: as soon
   as a promotion happens, the next production-version read (once this
   cache entry expires) stops matching this process's embedder, and the
   service starts fail-secure UNKNOWN-ing every request until an operator
   restarts/redeploys it pointed at the newly-promoted weights (the
   existing, accepted manual step per TR-08's docstring). That IS the
   "atomic switch" guarantee this task is responsible for: all-or-nothing
   as observed by `/recognize`, never a request served against a torn
   combination of old-embedder-vs-new-gallery or vice versa. Building an
   actual per-version weight hot-reload mechanism is future work that
   belongs with a real model registry (see `models/loader.py`), out of
   scope here.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass
class _CachedVersion:
    value: str | None
    fetched_at_monotonic: float


class ProductionVersionCache:
    """Per-process, in-memory TTL cache in front of
    `gallery.get_current_production_model_version`. Like IN-06's event
    fallback buffer, this is deliberately NOT shared across ai-inference
    replicas/worker processes -- each process may lag up to `ttl_seconds`
    behind the true PRODUCTION row after a promotion, an explicit bounded
    trade-off for avoiding a DB round trip on every `/recognize` call."""

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl_seconds = ttl_seconds
        self._cached: _CachedVersion | None = None

    def get(self, cursor: Any) -> str | None:
        from ai_inference import gallery

        cached = self._cached
        now = time.monotonic()
        if cached is not None and (now - cached.fetched_at_monotonic) < self._ttl_seconds:
            return cached.value
        value = gallery.get_current_production_model_version(cursor)
        self._cached = _CachedVersion(value=value, fetched_at_monotonic=now)
        return value

    def invalidate(self) -> None:
        """Forces the next `get()` call to re-query regardless of TTL --
        exposed for tests; nothing in the request path calls this today
        (there is no promotion-notification channel into ai-inference, see
        module docstring point 2)."""
        self._cached = None


def embedder_matches_production(embedder_version: str, production_version: str) -> bool:
    """`True` iff this process's loaded embedder is the SAME model_version
    currently PRODUCTION, i.e. it is safe to compare an embedding this
    process computes against the gallery filtered to `production_version`.
    `False` means a version mismatch -- the caller MUST treat this exactly
    like "no PRODUCTION model" (fail-secure `UNKNOWN`), never proceed to
    gallery search with it."""
    return embedder_version == production_version
