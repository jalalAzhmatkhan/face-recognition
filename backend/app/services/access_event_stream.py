"""SSE live-stream generator for `GET /stream/access-events` (BE-11,
TSD §7, FSD-AI §3.5 FR-MON-01: "Live access-event feed... < 2 detik").

Split out from `app/routers/access_events.py` so the actual async-generator
logic (subscribe / filter / format / keep-alive / cleanup) can be unit
tested directly against a fake async Redis client, without driving a real
ASGI request/response round trip (see backend/tests/test_access_event_stream.py
and its module docstring for why a real HTTP round trip is a poor fit for
testing a stream that runs "forever").

Design decisions worth calling out (non-obvious):

  - A SEPARATE async Redis client is used here (`app/core/redis_client.py:
    get_async_redis_client`), NOT the sync client `policy_cache.py`/
    `access_event_service.py` use. `redis.asyncio.Redis.pubsub().get_message()`
    is a coroutine; using the sync client here would block the whole
    FastAPI event loop on every poll.
  - Filtering (`device_id`/`decision`) happens SERVER-SIDE, after the
    message is received off the shared `access-events` channel — Redis
    pub/sub has no server-side filtering, and the payload is small, so this
    is simply the straightforward way to keep the contract "the stream
    only shows events you asked to see" consistent with `GET
    /access-events`'s query filters.
  - `pubsub.get_message(..., timeout=...)` (rather than `pubsub.listen()`,
    which blocks indefinitely) is used specifically so the loop can wake up
    periodically even with no traffic, to (a) check `request.is_disconnected()`
    and (b) emit a keep-alive comment so intermediate proxies/load balancers
    don't time out an idle connection.
  - Cleanup (`unsubscribe` + `close`) lives in a single `finally` block, so
    it runs identically whether the loop exits because the client
    disconnected (`request.is_disconnected()` returns True), the generator
    is cancelled (`asyncio.CancelledError` — e.g. the ASGI server tearing
    down the task on transport close), or `.aclose()` is called on the
    generator directly (as tests do). Never leaking the pubsub connection is
    the whole point of this block.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Protocol

from app.models.enums import AccessDecision
from app.services.access_event_service import ACCESS_EVENTS_CHANNEL

logger = logging.getLogger(__name__)

#: How often to poll Redis for a new pub/sub message before giving the loop
#: a chance to check for client disconnect. Small relative to PING_INTERVAL
#: so disconnects are noticed quickly without busy-looping.
GET_MESSAGE_POLL_TIMEOUT_SECONDS = 1.0

#: How often to emit a keep-alive comment on an otherwise idle stream, so
#: intermediate proxies/load balancers don't consider the connection dead.
PING_INTERVAL_SECONDS = 15.0


class DisconnectCheckable(Protocol):
    async def is_disconnected(self) -> bool: ...


def _matches_filters(
    payload: dict,
    *,
    device_id: uuid.UUID | None,
    decision: AccessDecision | None,
) -> bool:
    if device_id is not None and payload.get("device_id") != str(device_id):
        return False
    if decision is not None and payload.get("decision") != decision.value:
        return False
    return True


async def stream_access_events(
    async_redis_client,
    request: DisconnectCheckable | None,
    *,
    device_id: uuid.UUID | None = None,
    decision: AccessDecision | None = None,
) -> AsyncIterator[str]:
    """Yield SSE-formatted (`data: {...}\\n\\n` / `: keep-alive\\n\\n`) chunks
    for events published to the `access-events` Redis channel, filtered
    server-side by `device_id`/`decision` when given.

    `request` is optional (and only needs an async `is_disconnected()`
    method — see `DisconnectCheckable`) purely so this generator can be
    unit-tested without a real `fastapi.Request`.
    """
    pubsub = async_redis_client.pubsub()
    await pubsub.subscribe(ACCESS_EVENTS_CHANNEL)
    loop = asyncio.get_event_loop()
    last_activity = loop.time()
    try:
        while True:
            if request is not None and await request.is_disconnected():
                break

            try:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=GET_MESSAGE_POLL_TIMEOUT_SECONDS,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("access_event_stream_read_failed")
                break

            now = loop.time()
            if message is not None and message.get("type") == "message":
                raw = message.get("data")
                try:
                    payload = json.loads(raw)
                except (TypeError, ValueError):
                    logger.warning("access_event_stream_malformed_payload")
                    continue
                last_activity = now
                if _matches_filters(payload, device_id=device_id, decision=decision):
                    yield f"data: {json.dumps(payload)}\n\n"
            elif now - last_activity >= PING_INTERVAL_SECONDS:
                last_activity = now
                yield ": keep-alive\n\n"
    finally:
        try:
            await pubsub.unsubscribe(ACCESS_EVENTS_CHANNEL)
        except Exception:
            logger.warning("access_event_stream_unsubscribe_failed")
        try:
            await pubsub.close()
        except Exception:
            logger.warning("access_event_stream_close_failed")
