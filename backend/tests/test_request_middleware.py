"""Tests for `RequestIDMiddleware` — specifically, the requests it cannot see.

`main.py` awaited the downstream app with no `try`/`finally`, so the logging and
`record_request` calls that follow it were skipped whenever an exception propagated.
Starlette hoists the `@app.exception_handler(Exception)` catch-all into
`ServerErrorMiddleware`, which sits *outside* `RequestIDMiddleware` — so unhandled
exceptions went past it and were never recorded at all. The request log showed only
successes. That is not a cosmetic gap: while diagnosing issue #13 I read "586 stream
requests, zero non-2xx" off those logs and concluded the server was healthy. The logs
could not have shown otherwise.

**A client disconnect does not take that path**, which is worth being explicit about
because I first assumed it did. Uvicorn's `send` is:

    if self.disconnected:
        return

— a silent no-op. It raises nothing. `FileResponse` reads on to EOF, sending into a
closed socket, and returns normally. So an aborted stream *is* recorded, as a clean 200
whose duration is however long the listener stayed before skipping.

That turned out to be the more damaging problem, and it is measured, not theorised: one
aborted stream on the NAS logged `duration_ms: 1424.56`, and the p95 for the whole
five-minute window was `1424.56`. **A single skipped track defined p95 for every other
request.** Hence the transfer/API split in `TestTransfersDoNotDefinePercentiles`.

These drive the ASGI callable directly rather than through `TestClient`, which completes
every request it starts and so cannot express any of these cases.
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

    def record_request(self, method, route, status_code, duration_ms, query_count=0, outcome="completed", transfer=False):  # type: ignore[override]
        self.calls.append({
            "method": method,
            "route": route,
            "status_code": status_code,
            "duration_ms": duration_ms,
            "query_count": query_count,
            "outcome": outcome,
            "transfer": transfer,
        })
        super().record_request(
            method, route, status_code, duration_ms, query_count, outcome=outcome, transfer=transfer
        )


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
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [(b"content-type", b"application/json")],
    })
    await send({"type": "http.response.body", "body": b"fine"})


async def audio_app(scope, receive, send):
    """What the client actually walks away from."""
    await send({
        "type": "http.response.start",
        "status": 206,
        "headers": [(b"content-type", b"audio/mpeg")],
    })
    await send({"type": "http.response.body", "body": b"...."})


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


class TestTransferClassification:
    async def test_audio_response_is_marked_as_a_transfer(self, collector):
        await drive(audio_app)
        assert collector.calls[0]["transfer"] is True

    async def test_json_response_is_not(self, collector):
        await drive(ok_app)
        assert collector.calls[0]["transfer"] is False

    async def test_content_type_with_parameters_still_matches(self, collector):
        async def app(scope, receive, send):
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"Content-Type", b"audio/mpeg; charset=binary")],
            })
            await send({"type": "http.response.body", "body": b""})

        await drive(app)
        assert collector.calls[0]["transfer"] is True

    async def test_response_with_no_content_type_is_not_a_transfer(self, collector):
        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        await drive(app)
        assert collector.calls[0]["transfer"] is False


class TestTransfersDoNotDefinePercentiles:
    """Measured, not theorised.

    One stream aborted after ~1.4s on the NAS logged `duration_ms: 1424.56`, and the
    p95 for the entire five-minute window came back as `1424.56` — a single skipped
    track setting the latency figure for every other request in the window. Since #15
    is judged on that p95 during a library sync, it has to mean something first.
    """

    def test_one_aborted_stream_does_not_set_p95(self):
        c = MetricsCollector()
        for _ in range(9):
            c.record_request("GET", "/api/v1/thing", 200, 50.0)
        # A listener who played 40s of a track and skipped: a clean 200, 40s elapsed.
        c.record_request("GET", "/api/v1/tracks/{id}/stream", 200, 40000.0, transfer=True)

        req = c.get_snapshot()["request_metrics"]

        assert req["duration_p95_ms"] < 100, "listening time is not API latency"
        assert req["transfer_p95_ms"] == 40000.0, "but it is still reported"
        assert req["transfer_requests"] == 1

    def test_transfers_do_not_move_the_error_rate(self):
        c = MetricsCollector()
        for _ in range(9):
            c.record_request("GET", "/api/v1/thing", 200, 10.0)
        c.record_request("GET", "/api/v1/tracks/{id}/stream", 200, 9000.0, transfer=True)

        assert c.get_snapshot()["request_metrics"]["error_rate"] == 0.0

    def test_a_window_of_only_transfers_reports_no_api_latency(self):
        c = MetricsCollector()
        c.record_request("GET", "/api/v1/tracks/{id}/stream", 200, 9000.0, transfer=True)

        req = c.get_snapshot()["request_metrics"]
        assert req["duration_p95_ms"] == 0.0
        assert req["error_rate"] == 0.0
        assert req["transfer_requests"] == 1
        assert req["total_requests"] == 1

    def test_transfers_still_appear_in_top_routes(self):
        """Excluded from the percentiles, not hidden."""
        c = MetricsCollector()
        c.record_request("GET", "/api/v1/tracks/{id}/stream", 200, 9000.0, transfer=True)

        routes = [r["route"] for r in c.get_snapshot()["request_metrics"]["top_routes"]]
        assert "/api/v1/tracks/{id}/stream" in routes


class TestDoesNotPoisonMetrics:
    def test_disconnects_are_excluded_from_percentiles(self):
        c = MetricsCollector()
        for _ in range(9):
            c.record_request("GET", "/api/v1/thing", 200, 50.0)
        c.record_request("GET", "/api/v1/thing", 500, 40000.0, outcome="client_disconnect")

        assert c.get_snapshot()["request_metrics"]["duration_p95_ms"] < 100

    def test_disconnects_do_not_count_as_errors(self):
        """Skipping a track is normal use, not a server error."""
        c = MetricsCollector()
        for _ in range(9):
            c.record_request("GET", "/api/v1/thing", 200, 10.0)
        c.record_request("GET", "/api/v1/thing", 500, 5000.0, outcome="client_disconnect")

        assert c.get_snapshot()["request_metrics"]["error_rate"] == 0.0

    def test_disconnects_are_counted_separately(self):
        """Excluded from the error rate, but not thrown away."""
        c = MetricsCollector()
        c.record_request("GET", "/api/v1/thing", 200, 10.0)
        c.record_request("GET", "/api/v1/thing", 500, 5000.0, outcome="client_disconnect")
        c.record_request("GET", "/api/v1/thing", 500, 5000.0, outcome="client_disconnect")

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
        c.record_request("GET", "/api/v1/thing", 500, 5000.0, outcome="client_disconnect")

        req = c.get_snapshot()["request_metrics"]
        assert req["error_rate"] == 0.0
        assert req["duration_p95_ms"] == 0.0
        assert req["client_disconnects"] == 1

    def test_keyword_args_default_to_todays_behaviour(self):
        """Existing call sites pass five positional args and must keep working."""
        c = MetricsCollector()
        c.record_request("GET", "/api/v1/thing", 200, 10.0, 3)

        req = c.get_snapshot()["request_metrics"]
        assert req["total_requests"] == 1
        assert req["duration_p95_ms"] == 10.0  # counted as an API request
        assert req["transfer_requests"] == 0


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
