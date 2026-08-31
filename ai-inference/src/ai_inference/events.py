"""Access-event emission to backend's `POST /access-events` (IN-06, TSD SS1.3,
FR-INF-04): fire-and-forget from ai-inference's hot path, with a bounded
in-memory fallback buffer for brief backend outages.

**Design** (TSD SS1.3): "`ai-inference` ... must not call slow services
synchronously (access-event writes are fire-and-forget via queue with local
fallback buffer in memory)." ai-inference has no message broker of its own
(the Celery/Redis broker in TSD SS1.1 belongs to backend/ai-training) --
"queue" here means: the call is dispatched via FastAPI `BackgroundTasks`
(`ai_inference.main`'s `/recognize` handler) so it runs AFTER the response is
already on the wire, never adding to the decision-latency budget (NFR-PRF-01,
IN-05). If the backend call itself fails (timeout, connection error, 5xx),
the payload is appended to a bounded in-process buffer instead of being
dropped, so it can be retried once the outage clears.

**What "brief outage" means here, precisely**: the buffer
(`_buffer`/`_buffer_max_size` below) is plain process memory -- NOT persisted
to disk, NOT shared across ai-inference replicas or worker processes. A
process restart, or an outage that outlasts the buffer filling up (oldest
event evicted to make room, see `_enqueue`), loses those events. This matches
TSD's literal wording ("local fallback buffer in memory") -- a durable outbox
would be a `backend`-owned Celery/Postgres concern, out of scope here.

**Auth**: `POST /access-events` is device-authenticated (BE-10), not a
service-to-service credential -- there is no separate ai-inference-to-backend
auth path. The SAME device bearer token (`<credential_id>.<secret>`) that
authenticated the originating `/recognize` call is forwarded verbatim (see
`ai_inference.auth_dependency.get_current_device_bearer_token`), since
`POST /access-events` derives `device_id` from that token, never from the
request body (mirrors `POST /recognize`'s own device auth).

Two entry points:
- `emit_access_event_background`: what `ai_inference.main` hands to
  `BackgroundTasks.add_task` for every `/recognize` call.
- `run_flush_loop`: an `asyncio` task started from the app lifespan that
  periodically retries whatever is sitting in the buffer.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ai_inference.metrics import access_events_total

if TYPE_CHECKING:
    from ai_inference.config import Settings


@dataclass(frozen=True)
class BufferedAccessEvent:
    """One access-event POST that couldn't be delivered on the first try."""

    payload: dict[str, Any]
    device_bearer_token: str
    queued_at_monotonic: float = field(default_factory=time.monotonic)


_buffer: deque[BufferedAccessEvent] = deque()
_buffer_max_size: int = 1000


def configure_buffer(max_size: int) -> None:
    """Sets the buffer bound (called once at app startup from
    `Settings.access_event_buffer_max_size`). Does not resize `_buffer`
    itself -- eviction is enforced lazily by `_enqueue` on the next append,
    so shrinking mid-run doesn't retroactively truncate what's already
    queued."""
    global _buffer_max_size
    _buffer_max_size = max_size


def buffered_event_count() -> int:
    """Exposed for tests and `/healthz`-style introspection."""
    return len(_buffer)


def _enqueue(event: BufferedAccessEvent) -> None:
    """Appends, evicting the OLDEST entry first if already at capacity --
    a deliberate, observable trade-off (see module docstring) rather than
    growing unbounded or silently refusing new events."""
    if len(_buffer) >= _buffer_max_size:
        _buffer.popleft()
        access_events_total.labels(result="dropped").inc()
    _buffer.append(event)


def _post_event(settings: Settings, device_bearer_token: str, payload: dict[str, Any]) -> bool:
    """One synchronous POST attempt to backend's `/access-events`. Returns
    `True` on a 2xx response, `False` for anything else (timeout, connection
    error, non-2xx status) -- never raises, so callers never need their own
    try/except around this."""
    import httpx

    url = settings.backend_base_url.rstrip("/") + settings.backend_access_events_path
    try:
        response = httpx.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {device_bearer_token}"},
            timeout=settings.access_event_timeout_seconds,
        )
    except httpx.HTTPError:
        return False
    return 200 <= response.status_code < 300


def emit_access_event_background(
    settings: Settings, device_bearer_token: str, payload: dict[str, Any]
) -> None:
    """The `BackgroundTasks` target for every `/recognize` call: runs AFTER
    the response is already sent, so it may take its time (bounded by
    `access_event_timeout_seconds`) without affecting decision latency. On
    failure, buffers the event for `run_flush_loop` to retry instead of
    dropping it outright."""
    if not settings.backend_base_url:
        # No backend configured (dev/test): FR-INF-04 needs a real backend to
        # report to. Skipping silently (never buffering) avoids an
        # ever-growing buffer that no retry loop could ever successfully
        # flush.
        return
    if _post_event(settings, device_bearer_token, payload):
        access_events_total.labels(result="sent").inc()
        return
    _enqueue(BufferedAccessEvent(payload=payload, device_bearer_token=device_bearer_token))
    access_events_total.labels(result="buffered").inc()


def flush_buffered_events(settings: Settings) -> None:
    """Retries buffered events oldest-first. Stops at the FIRST failure
    rather than draining the whole buffer on every call -- if backend is
    still down, attempting every remaining item is wasted latency on this
    (synchronous, blocking) call and needlessly hammers a service that's
    already struggling; the rest simply wait for the next scheduled flush."""
    while _buffer:
        event = _buffer[0]
        if not _post_event(settings, event.device_bearer_token, event.payload):
            access_events_total.labels(result="retry_failed").inc()
            return
        _buffer.popleft()
        access_events_total.labels(result="retried_ok").inc()


async def run_flush_loop(settings: Settings) -> None:
    """Background `asyncio` task started from the app lifespan
    (`ai_inference.main`): sleeps `access_event_retry_interval_seconds`
    between attempts, forever, until cancelled at shutdown. The actual flush
    is synchronous/blocking (plain `httpx.post` calls) so it runs via
    `asyncio.to_thread` -- otherwise a slow/unreachable backend would stall
    the event loop for up to `access_event_timeout_seconds` per buffered
    item, which would defeat the entire fire-and-forget premise for any
    concurrently in-flight `/recognize` request being served on that loop."""
    while True:
        await asyncio.sleep(settings.access_event_retry_interval_seconds)
        if _buffer:
            await asyncio.to_thread(flush_buffered_events, settings)
