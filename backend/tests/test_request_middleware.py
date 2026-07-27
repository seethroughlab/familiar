"""Tests for `RequestIDMiddleware` — specifically, the requests it cannot see.

`main.py` awaited the downstream app with no `try`/`finally`, so the logging and
`record_request` calls that follow it were skipped whenever the request did not return
normally. Two ways that happens:

- **Client disconnect.** Uvicorn raises `CancelledError` into the task when the socket
  goes away. Every aborted audio stream — every skipped track — took this path.
- **Unhandled exception.** Starlette hoists the `@app.exception_handler(Exception)`
  catch-all into `ServerErrorMiddleware`, which sits *outside* `RequestIDMiddleware`, so
  the exception propagates through the middleware before anything catches it.

The result was that `metrics_summary` and the request log recorded only successes. That
is not a cosmetic gap: while diagnosing issue #13 I read "586 stream requests, zero
non-2xx" off those logs and concluded the server was healthy. The logs could not have
shown otherwise. **These are the regression tests for that wrong conclusion.**

They drive the ASGI callable directly rather than through `TestClient`, because
`TestClient` completes every request it starts — it cannot abort mid-body, which is the
case that matters most.

The trap in the obvious fix has its own tests below (`TestDoesNotPoisonMetrics`): a bare
`try`/`finally` would record an aborted 40-second stream as a *successful* 206 that took
40000 ms, because `status_code` is set as soon as the response *starts*. That inflates
p95 with what is really listening time and reports failures as successes — worse than
recording nothing, since #15 depends on that p95 being trustworthy.
"""

import asyncio

import pytest

from app.main import RequestIDMiddleware, create_error_response
from app.services.metrics import MetricsCollector


class RecordingCollector(MetricsCollector):
    """A real collector that also keeps the calls, so assertions can read them back."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[dict] = []

    def record_request(self, method, route, status_code, duration_ms, query_count=0, outcome="completed"):  # type: ignore[override]
        self.calls.append({
            "method": method,
            "route": route,
            "status_code": status_code,
            "duration_ms": duration_ms,
            "query_count": query_count,
            "outcome": outcome,
        })
        super().record_request(method, route, status_code, duration_ms, query_count, outcome=outcome)


@pytest.fixture()
def collector(monkeypatch):
    """Swap the singleton for a recording one, for the duration of a test."""
    rec = RecordingCollector()
    monkeypatch.setattr("app.services.metrics.get_metrics_collector", lambda: rec)
    return rec


def make_scope(path: str = "/api/v1/thing", method: str = "GET") -> dict:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("127.0.0.1", 54321),
        "server": ("127.0.0.1", 8000),
    }


async def empty_receive() -> dict:
    return {"type": "http.disconnect"}


def make_send():
    """A `send` that records the messages it is given."""
    messages: list[dict] = []

    async def send(message):
        messages.append(message)

    return send, messages


async def drive(downstream, path="/api/v1/thing"):
    """Run `downstream` under the middleware. Returns (sent_messages, raised_or_None)."""
    send, messages = make_send()
    middleware = RequestIDMiddleware(downstream)
    raised = None
    try:
        await middleware(make_scope(path), empty_receive, send)
    except BaseException as exc:  # noqa: BLE001 — the point is to capture whatever escapes
        raised = exc
    return messages, raised


# --- downstream apps ------------------------------------------------------------------

async def ok_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"fine"})


async def raising_app(scope, receive, send):
    raise RuntimeError("handler blew up")


async def stream_then_disconnect_app(scope, receive, send):
    """A range response that starts, sends some body, then the client goes away."""
    await send({"type": "http.response.start", "status": 206, "headers": []})
    await send({"type": "http.response.body", "body": b"audio", "more_body": True})
    raise asyncio.CancelledError()


async def disconnect_before_response_app(scope, receive, send):
    raise asyncio.CancelledError()


# --- tests ----------------------------------------------------------------------------


class TestNormalRequests:
    async def test_records_a_completed_request(self, collector):
        messages, raised = await drive(ok_app)

        assert raised is None
        assert len(collector.calls) == 1
        call = collector.calls[0]
        assert call["outcome"] == "completed"
        assert call["status_code"] == 200

    async def test_still_adds_the_request_id_header(self, collector):
        messages, _ = await drive(ok_app)

        start = next(m for m in messages if m["type"] == "http.response.start")
        header_names = [k for k, _ in start["headers"]]
        assert b"x-request-id" in header_names

    async def test_skipped_paths_are_not_recorded(self, collector):
        """`/health` and static assets bypass timing entirely — unchanged behaviour."""
        await drive(ok_app, path="/health")
        assert collector.calls == []


class TestClientDisconnect:
    """The case that made every aborted audio stream invisible."""

    async def test_disconnect_mid_body_is_recorded(self, collector):
        _, raised = await drive(stream_then_disconnect_app)

        assert isinstance(raised, asyncio.CancelledError), "CancelledError must propagate"
        assert len(collector.calls) == 1, "an aborted stream must still be recorded"
        assert collector.calls[0]["outcome"] == "client_disconnect"

    async def test_disconnect_keeps_the_status_already_sent(self, collector):
        """Not 500.

        The response *started* — the client received a 206 and some audio. Reporting it
        as a 500 would invent a server error that never happened.
        """
        await drive(stream_then_disconnect_app)
        assert collector.calls[0]["status_code"] == 206

    async def test_disconnect_before_response_is_500(self, collector):
        """Distinguishable from the above: the server never got to respond at all."""
        _, raised = await drive(disconnect_before_response_app)

        assert isinstance(raised, asyncio.CancelledError)
        assert collector.calls[0]["outcome"] == "client_disconnect"
        assert collector.calls[0]["status_code"] == 500


class TestUnhandledException:
    async def test_error_is_recorded_and_propagates(self, collector):
        """It must reach `ServerErrorMiddleware`, which is what produces the 500 body."""
        _, raised = await drive(raising_app)

        assert isinstance(raised, RuntimeError)
        assert len(collector.calls) == 1
        assert collector.calls[0]["outcome"] == "error"
        assert collector.calls[0]["status_code"] == 500

    async def test_recorded_exactly_once(self, collector):
        """A `finally` that also ran on the exception path would double-count."""
        await drive(raising_app)
        assert len(collector.calls) == 1


class TestDoesNotPoisonMetrics:
    """A bare try/finally would be worse than the bug. These pin down why."""

    def test_disconnects_are_excluded_from_percentiles(self):
        c = MetricsCollector()
        for _ in range(9):
            c.record_request("GET", "/api/v1/thing", 200, 50.0)
        # One aborted stream that the user listened to for 40 seconds.
        c.record_request("GET", "/api/v1/stream", 206, 40000.0, outcome="client_disconnect")

        req = c.get_snapshot()["request_metrics"]

        assert req["duration_p95_ms"] < 100, (
            "a 40s listen recorded as latency would put p95 at 40000ms and make the "
            "measurement for #15 meaningless"
        )

    def test_disconnects_do_not_count_as_errors(self):
        """Skipping a track is normal use, not a server error."""
        c = MetricsCollector()
        for _ in range(9):
            c.record_request("GET", "/api/v1/thing", 200, 10.0)
        c.record_request("GET", "/api/v1/stream", 206, 5000.0, outcome="client_disconnect")

        assert c.get_snapshot()["request_metrics"]["error_rate"] == 0.0

    def test_disconnects_are_counted_separately(self):
        """Excluded from the error rate, but not thrown away — this is the #13 signal."""
        c = MetricsCollector()
        c.record_request("GET", "/api/v1/thing", 200, 10.0)
        c.record_request("GET", "/api/v1/stream", 206, 5000.0, outcome="client_disconnect")
        c.record_request("GET", "/api/v1/stream", 206, 5000.0, outcome="client_disconnect")

        req = c.get_snapshot()["request_metrics"]
        assert req["client_disconnects"] == 2
        assert req["total_requests"] == 3

    def test_real_errors_still_count(self):
        c = MetricsCollector()
        for _ in range(9):
            c.record_request("GET", "/api/v1/thing", 200, 10.0)
        c.record_request("GET", "/api/v1/thing", 500, 10.0, outcome="error")

        assert c.get_snapshot()["request_metrics"]["error_rate"] == 0.1

    def test_snapshot_with_only_disconnects_does_not_divide_by_zero(self):
        c = MetricsCollector()
        c.record_request("GET", "/api/v1/stream", 206, 5000.0, outcome="client_disconnect")

        req = c.get_snapshot()["request_metrics"]
        assert req["error_rate"] == 0.0
        assert req["duration_p95_ms"] == 0.0
        assert req["client_disconnects"] == 1

    def test_outcome_defaults_to_completed(self):
        """Existing call sites pass five positional args and must keep working."""
        c = MetricsCollector()
        c.record_request("GET", "/api/v1/thing", 200, 10.0, 3)
        assert c.get_snapshot()["request_metrics"]["total_requests"] == 1


class TestErrorResponsesCarryTheRequestID:
    """`ServerErrorMiddleware` is outside `RequestIDMiddleware`, so the 500 it emits never
    passes through `send_with_request_id` and got no `x-request-id` header — on exactly
    the responses you most want to correlate with a log line."""

    def test_header_is_set_when_a_request_id_is_known(self):
        response = create_error_response(500, "Internal server error", request_id="abc12345")
        assert response.headers.get("x-request-id") == "abc12345"

    def test_body_still_carries_it_too(self):
        response = create_error_response(500, "Internal server error", request_id="abc12345")
        assert b"abc12345" in response.body

    def test_no_header_without_a_request_id(self):
        response = create_error_response(404, "Not found")
        assert "x-request-id" not in response.headers
