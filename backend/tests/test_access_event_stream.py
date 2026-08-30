"""Unit tests for app/services/access_event_stream.py (BE-11, FR-MON-01).

No real Redis: `FakeAsyncPubSub`/`FakeAsyncRedis` are tiny in-memory
stand-ins for `redis.asyncio.Redis().pubsub()` that support just the
subscribe/get_message/unsubscribe/close surface `stream_access_events`
uses.

Because `stream_access_events` is an async generator that (by design) runs
"forever" until the client disconnects, these tests drive it directly as an
async generator — pulling a fixed number of items with `__anext__()` (or
closing it early with `aclose()`) — rather than going through a real HTTP
round trip, which would either hang or require timing-sensitive network
plumbing to terminate reliably. This project has no pytest-asyncio/anyio
pytest plugin installed, so each test is a plain sync function that drives
its async body via `asyncio.run(...)`.
"""

import asyncio
import json

from app.models.enums import AccessDecision
from app.services.access_event_stream import (
    GET_MESSAGE_POLL_TIMEOUT_SECONDS,
    stream_access_events,
)


class FakeAsyncPubSub:
    def __init__(self, broker: "FakeAsyncRedis") -> None:
        self._broker = broker
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self.subscribed_channels: list[str] = []
        self.unsubscribed_channels: list[str] = []
        self.closed = False

    async def subscribe(self, channel: str) -> None:
        self.subscribed_channels.append(channel)
        self._broker._register(channel, self._queue)

    async def unsubscribe(self, channel: str | None = None) -> None:
        self.unsubscribed_channels.append(channel)

    async def get_message(self, ignore_subscribe_messages: bool = True, timeout: float = 1.0):
        try:
            data = await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except TimeoutError:
            return None
        return {"type": "message", "data": data}

    async def close(self) -> None:
        self.closed = True


class FailingGetMessagePubSub(FakeAsyncPubSub):
    async def get_message(self, ignore_subscribe_messages: bool = True, timeout: float = 1.0):
        raise ConnectionError("simulated Redis outage")


class FakeAsyncRedis:
    def __init__(self, pubsub_cls: type[FakeAsyncPubSub] = FakeAsyncPubSub) -> None:
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._pubsub_cls = pubsub_cls
        self.last_pubsub: FakeAsyncPubSub | None = None

    def pubsub(self) -> FakeAsyncPubSub:
        instance = self._pubsub_cls(self)
        self.last_pubsub = instance
        return instance

    def _register(self, channel: str, queue: asyncio.Queue) -> None:
        self._subscribers.setdefault(channel, []).append(queue)

    async def publish(self, channel: str, message: str) -> int:
        queues = self._subscribers.get(channel, [])
        for queue in queues:
            await queue.put(message)
        return len(queues)


class FakeRequest:
    """Async `is_disconnected()` stand-in. Returns False for the first
    `disconnect_after` calls, then True — simulating a client that stays
    connected for a while and then goes away."""

    def __init__(self, disconnect_after: int | None = None) -> None:
        self._calls = 0
        self._disconnect_after = disconnect_after

    async def is_disconnected(self) -> bool:
        self._calls += 1
        if self._disconnect_after is None:
            return False
        return self._calls > self._disconnect_after


def _event_payload(**overrides) -> dict:
    payload = {
        "id": "11111111-1111-1111-1111-111111111111",
        "occurred_at": "2026-08-30T10:00:00+00:00",
        "device_id": "22222222-2222-2222-2222-222222222222",
        "decision": "GRANTED",
        "matched_user_id": None,
        "similarity": 0.98,
        "liveness_score": 0.99,
        "model_version": "v1",
        "latency_ms": 120,
        "door_command_issued": True,
    }
    payload.update(overrides)
    return payload


def test_stream_yields_published_event_as_sse_data_line() -> None:
    async def run() -> None:
        redis_client = FakeAsyncRedis()
        gen = stream_access_events(redis_client, request=None)
        # Prime the generator up to its first `get_message` await, then
        # publish, then collect the yielded chunk.
        task = asyncio.ensure_future(gen.__anext__())
        await asyncio.sleep(0)  # let subscribe() run
        await redis_client.publish("access-events", json.dumps(_event_payload()))
        chunk = await task

        assert chunk.startswith("data: ")
        assert chunk.endswith("\n\n")
        parsed = json.loads(chunk[len("data: ") : -2])
        assert parsed["decision"] == "GRANTED"
        assert parsed["door_command_issued"] is True

        await gen.aclose()

    asyncio.run(run())


def test_stream_filters_out_events_not_matching_device_id() -> None:
    async def run() -> None:
        redis_client = FakeAsyncRedis()
        target_device = "33333333-3333-3333-3333-333333333333"
        gen = stream_access_events(redis_client, request=None, device_id=target_device)

        task = asyncio.ensure_future(gen.__anext__())
        await asyncio.sleep(0)
        # Non-matching event first, then a matching one.
        await redis_client.publish(
            "access-events", json.dumps(_event_payload(device_id="other-device"))
        )
        await redis_client.publish(
            "access-events", json.dumps(_event_payload(device_id=target_device))
        )
        chunk = await task

        parsed = json.loads(chunk[len("data: ") : -2])
        assert parsed["device_id"] == target_device

        await gen.aclose()

    asyncio.run(run())


def test_stream_filters_out_events_not_matching_decision() -> None:
    async def run() -> None:
        redis_client = FakeAsyncRedis()
        gen = stream_access_events(redis_client, request=None, decision=AccessDecision.DENIED)

        task = asyncio.ensure_future(gen.__anext__())
        await asyncio.sleep(0)
        await redis_client.publish("access-events", json.dumps(_event_payload(decision="GRANTED")))
        await redis_client.publish("access-events", json.dumps(_event_payload(decision="DENIED")))
        chunk = await task

        parsed = json.loads(chunk[len("data: ") : -2])
        assert parsed["decision"] == "DENIED"

        await gen.aclose()

    asyncio.run(run())


def test_stream_ignores_malformed_payload_and_continues() -> None:
    async def run() -> None:
        redis_client = FakeAsyncRedis()
        gen = stream_access_events(redis_client, request=None)

        task = asyncio.ensure_future(gen.__anext__())
        await asyncio.sleep(0)
        await redis_client.publish("access-events", "not valid json")
        await redis_client.publish("access-events", json.dumps(_event_payload()))
        chunk = await task

        assert json.loads(chunk[len("data: ") : -2])["decision"] == "GRANTED"

        await gen.aclose()

    asyncio.run(run())


def test_stream_stops_and_cleans_up_when_client_disconnects() -> None:
    async def run() -> None:
        redis_client = FakeAsyncRedis()
        request = FakeRequest(disconnect_after=0)  # disconnected from the very first check
        gen = stream_access_events(redis_client, request=request)

        # The generator must stop on its own (StopAsyncIteration) rather
        # than yielding anything, and must unsubscribe + close the pubsub.
        got_stop_iteration = False
        try:
            await gen.__anext__()
        except StopAsyncIteration:
            got_stop_iteration = True

        assert got_stop_iteration
        pubsub = redis_client.last_pubsub
        assert pubsub is not None
        assert pubsub.unsubscribed_channels == ["access-events"]
        assert pubsub.closed is True

    asyncio.run(run())


def test_stream_unsubscribes_and_closes_pubsub_on_generator_close() -> None:
    """Simulates the ASGI server tearing down the streaming task when the
    HTTP client disconnects mid-stream (Starlette calls `aclose()` on the
    generator in that case)."""

    async def run() -> None:
        redis_client = FakeAsyncRedis()
        gen = stream_access_events(redis_client, request=None)

        task = asyncio.ensure_future(gen.__anext__())
        await asyncio.sleep(0)  # let it subscribe and start waiting
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        await gen.aclose()

        pubsub = redis_client.last_pubsub
        assert pubsub is not None
        assert pubsub.unsubscribed_channels == ["access-events"]
        assert pubsub.closed is True

    asyncio.run(run())


def test_stream_emits_keep_alive_when_idle_past_ping_interval(monkeypatch) -> None:
    """Rather than sleeping the real PING_INTERVAL_SECONDS (15s) in a test,
    monkeypatch the poll timeout down so an idle loop iteration crosses the
    ping threshold quickly, and monkeypatch the interval itself to
    something small too."""
    import app.services.access_event_stream as stream_module

    monkeypatch.setattr(stream_module, "PING_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(stream_module, "GET_MESSAGE_POLL_TIMEOUT_SECONDS", 0.01)

    async def run() -> None:
        redis_client = FakeAsyncRedis()
        gen = stream_access_events(redis_client, request=None)
        chunk = await gen.__anext__()
        assert chunk == ": keep-alive\n\n"
        await gen.aclose()

    asyncio.run(run())


def test_stream_stops_on_redis_read_error() -> None:
    async def run() -> None:
        redis_client = FakeAsyncRedis(pubsub_cls=FailingGetMessagePubSub)
        gen = stream_access_events(redis_client, request=None)

        got_stop_iteration = False
        try:
            await gen.__anext__()
        except StopAsyncIteration:
            got_stop_iteration = True

        assert got_stop_iteration
        pubsub = redis_client.last_pubsub
        assert pubsub is not None
        assert pubsub.closed is True

    asyncio.run(run())


def test_get_message_poll_timeout_is_shorter_than_ping_interval() -> None:
    """Sanity check on the module's own constants: the poll timeout must
    stay well under the ping interval, or a single idle poll could overshoot
    it and delay the keep-alive."""
    assert GET_MESSAGE_POLL_TIMEOUT_SECONDS < 15.0
