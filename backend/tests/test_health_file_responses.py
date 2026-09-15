"""`GET /health/file-responses` — the limiters' counters, reported at last (ADR-0112, ADR-0118).

Both download incidents were diagnosed from the NAS's syslog because the server recorded nothing
about the pressure it was under. The counters have existed since 2026-09-07; this is the first
thing that reads them.
"""

import pytest

from app.api import concurrency


@pytest.fixture()
def fresh_limiters(monkeypatch):
    """The process-wide limiters, replaced so a count here is a count this test made."""
    stream = concurrency.FileResponseLimiter()
    encoder = concurrency.EncoderLimiter(limit=4)
    monkeypatch.setattr(concurrency, "limiter", stream)
    monkeypatch.setattr(concurrency, "encoder_limiter", encoder)
    return stream, encoder


class TestFileResponseHealth:
    def test_reports_the_limits_and_zeroes_at_rest(self, client, fresh_limiters):
        r = client.get("/api/v1/health/file-responses")
        assert r.status_code == 200
        body = r.json()
        assert body["stream"]["limit"] == concurrency.MAX_CONCURRENT_STREAM_RESPONSES
        assert body["stream"]["sync_limit"] == concurrency.MAX_CONCURRENT_SYNC_RESPONSES
        assert body["artwork"]["limit"] == concurrency.MAX_CONCURRENT_ARTWORK_RESPONSES
        assert body["encoder"]["limit"] == 4
        assert body["stream"]["in_flight"] == 0
        assert body["stream"]["refused_sync"] == 0
        assert body["encoder"]["waited"] == 0

    def test_a_refusal_and_a_peak_show_up(self, client, fresh_limiters):
        stream, _ = fresh_limiters
        # Fill the sync share, then one more: that one is refused and the peak is the share.
        for _ in range(stream.sync_limit):
            assert stream.try_acquire(is_sync=True)
        assert not stream.try_acquire(is_sync=True)

        body = client.get("/api/v1/health/file-responses").json()
        assert body["stream"]["refused_sync"] == 1
        assert body["stream"]["refused_interactive"] == 0
        assert body["stream"]["peak_sync_in_flight"] == stream.sync_limit
        assert body["stream"]["in_flight"] == stream.sync_limit

        for _ in range(stream.sync_limit):
            stream.release(is_sync=True)
        assert client.get("/api/v1/health/file-responses").json()["stream"]["in_flight"] == 0

    @pytest.mark.asyncio
    async def test_the_encoders_wait_count_is_reported(self, client, fresh_limiters):
        _, encoder = fresh_limiters
        for _ in range(encoder.limit):
            await encoder.acquire()
        # The fifth would wait; record that it would have, the way the limiter does, without
        # actually blocking the test on it.
        assert encoder._slots.locked()
        encoder.waited += 1
        body = client.get("/api/v1/health/file-responses").json()
        assert body["encoder"]["in_flight"] == encoder.limit
        assert body["encoder"]["peak_in_flight"] == encoder.limit
        assert body["encoder"]["waited"] == 1
        for _ in range(encoder.limit):
            encoder.release()
