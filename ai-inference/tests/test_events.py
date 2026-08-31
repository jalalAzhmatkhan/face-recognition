"""Unit tests for `ai_inference.events` (IN-06): pure Python + a monkeypatched
`httpx.post` -- no real network, no DB, no `ml` extra needed, must pass on
base CI."""

import httpx
import pytest

from ai_inference import events
from ai_inference.config import Settings

SETTINGS = Settings(backend_base_url="http://backend.invalid", access_event_timeout_seconds=0.5)
PAYLOAD = {"decision": "GRANTED", "matched_user_id": None, "similarity": 0.9}


@pytest.fixture(autouse=True)
def _reset_buffer():
    """Every test starts from a clean module-level buffer/bound -- these are
    process-global by design (see module docstring), so tests must reset
    them explicitly rather than relying on fixture-scoped instances."""
    events._buffer.clear()
    events.configure_buffer(1000)
    yield
    events._buffer.clear()
    events.configure_buffer(1000)


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


def test_emit_does_nothing_when_no_backend_configured() -> None:
    no_backend_settings = Settings(backend_base_url="")
    events.emit_access_event_background(no_backend_settings, "device-token", PAYLOAD)
    assert events.buffered_event_count() == 0


def test_emit_sends_successfully_and_does_not_buffer(monkeypatch) -> None:
    calls = []

    def fake_post(url, *, json, headers, timeout):
        calls.append((url, json, headers, timeout))
        return _FakeResponse(201)

    monkeypatch.setattr(httpx, "post", fake_post)
    events.emit_access_event_background(SETTINGS, "cred-id.secret", PAYLOAD)

    assert events.buffered_event_count() == 0
    assert len(calls) == 1
    url, json_body, headers, timeout = calls[0]
    assert url == "http://backend.invalid/api/v1/access-events"
    assert json_body == PAYLOAD
    assert headers == {"Authorization": "Bearer cred-id.secret"}
    assert timeout == 0.5


def test_emit_buffers_on_non_2xx_response(monkeypatch) -> None:
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse(503))
    events.emit_access_event_background(SETTINGS, "cred-id.secret", PAYLOAD)
    assert events.buffered_event_count() == 1


def test_emit_buffers_on_connection_error(monkeypatch) -> None:
    def raise_connect_error(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", raise_connect_error)
    events.emit_access_event_background(SETTINGS, "cred-id.secret", PAYLOAD)
    assert events.buffered_event_count() == 1


def test_buffer_evicts_oldest_when_full(monkeypatch) -> None:
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse(500))
    events.configure_buffer(2)

    events.emit_access_event_background(SETTINGS, "token", {"decision": "GRANTED", "seq": 1})
    events.emit_access_event_background(SETTINGS, "token", {"decision": "GRANTED", "seq": 2})
    events.emit_access_event_background(SETTINGS, "token", {"decision": "GRANTED", "seq": 3})

    assert events.buffered_event_count() == 2
    remaining_seqs = [event.payload["seq"] for event in events._buffer]
    assert remaining_seqs == [2, 3]  # oldest (seq=1) evicted


def test_flush_buffered_events_drains_on_success(monkeypatch) -> None:
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse(500))
    events.emit_access_event_background(SETTINGS, "token", {"decision": "GRANTED", "seq": 1})
    events.emit_access_event_background(SETTINGS, "token", {"decision": "GRANTED", "seq": 2})
    assert events.buffered_event_count() == 2

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse(201))
    events.flush_buffered_events(SETTINGS)
    assert events.buffered_event_count() == 0


def test_flush_buffered_events_stops_at_first_failure(monkeypatch) -> None:
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse(500))
    events.emit_access_event_background(SETTINGS, "token", {"decision": "GRANTED", "seq": 1})
    events.emit_access_event_background(SETTINGS, "token", {"decision": "GRANTED", "seq": 2})
    assert events.buffered_event_count() == 2

    # Still failing -- flush must leave BOTH items queued (stop at the first
    # failure), not discard the ones it merely tried and failed on.
    events.flush_buffered_events(SETTINGS)
    assert events.buffered_event_count() == 2
