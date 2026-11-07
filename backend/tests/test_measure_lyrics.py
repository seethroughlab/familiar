"""The measurement exists to tell an outage from a miss, so that is what is tested."""

import importlib.util
import sys
from pathlib import Path

import httpx
import pytest

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "measure_lyrics.py"
_spec = importlib.util.spec_from_file_location("measure_lyrics", _PATH)
assert _spec and _spec.loader
measure = importlib.util.module_from_spec(_spec)
sys.modules["measure_lyrics"] = measure
_spec.loader.exec_module(measure)


def _transport(handler) -> "measure.RecordingTransport":
    return measure.RecordingTransport(httpx.MockTransport(handler), min_interval=0)


async def _get(transport) -> None:
    async with httpx.AsyncClient(transport=transport, base_url="https://lrclib.test") as client:
        await client.get("/api/get")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 500, 503])
async def test_a_failing_server_is_transient_not_a_miss(status):
    transport = _transport(lambda _: httpx.Response(status))
    await _get(transport)
    assert measure.classify(False, False, transport.take()) == "transient"


@pytest.mark.asyncio
async def test_a_timeout_is_recorded_though_the_response_never_came():
    def handler(_):
        raise httpx.ConnectTimeout("no answer")

    transport = _transport(handler)
    with pytest.raises(httpx.ConnectTimeout):
        await _get(transport)

    exchanges = transport.take()
    assert exchanges[0].error == "ConnectTimeout"
    assert measure.classify(False, False, exchanges) == "transient"


@pytest.mark.asyncio
async def test_a_404_is_an_answer():
    transport = _transport(lambda _: httpx.Response(404))
    await _get(transport)
    assert measure.classify(False, False, transport.take()) == "miss"


@pytest.mark.asyncio
async def test_retry_after_holds_the_next_request():
    transport = _transport(lambda _: httpx.Response(429, headers={"Retry-After": "30"}))
    await _get(transport)
    assert transport.take()[0].retry_after == 30
    assert transport._hold_until > 0


def test_a_hit_stands_despite_an_earlier_failure():
    failed = measure.Exchange("/api/get", 500)
    assert measure.classify(True, True, [failed]) == "synced"
    assert measure.classify(True, False, [failed]) == "plain"


def test_a_run_with_transient_failures_is_not_valid():
    assert measure.summarize(["synced"] * 99 + ["miss"])["valid"] is True
    assert measure.summarize(["synced"] * 99 + ["transient"])["valid"] is False
