"""Tests for audio range-request streaming.

`app.api.streaming.stream_file` had no test coverage at all.
`test_stream_concurrency.py` looks like it covers this but does not: all three of its
tests use a random `uuid4()` that 404s before `stream_file` is ever reached, and they
assert `status_code in (200, 206, 404, 500)` — so even an unhandled exception passes.
Its `temp_audio_file` fixture is defined and never used by anything.

These drive the real endpoint against a real file on disk, so a byte returned wrong is
a byte that fails a test.

Several of these are expected to FAIL against the hand-rolled implementation and to pass
once it is replaced with Starlette's `FileResponse` (issue #13). They are written first
deliberately: a bug that cannot be demonstrated is a bug that has not been established.
"""

import tempfile
from pathlib import Path

import pytest

from tests.factories import insert_test_track

# Deterministic, and large enough that ranges are meaningful.
CONTENT = bytes(range(256)) * 64  # 16 KiB
CONTENT_LEN = len(CONTENT)


@pytest.fixture()
def audio_file():
    """A real file on disk for a track row to point at."""
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(CONTENT)
        f.flush()
        path = Path(f.name)
    yield path
    path.unlink(missing_ok=True)


@pytest.fixture()
async def streamable_track(async_db, audio_file):
    """A track whose file_path points at a real, readable file."""
    track = await insert_test_track(async_db, title="Streamable", file_path=str(audio_file))
    await async_db.commit()
    return track


class TestFullRequest:
    @pytest.mark.asyncio
    async def test_serves_the_whole_file(self, streamable_track, client):
        r = client.get(f"/api/v1/tracks/{streamable_track.id}/stream")
        assert r.status_code == 200
        assert r.content == CONTENT
        assert int(r.headers["content-length"]) == CONTENT_LEN

    @pytest.mark.asyncio
    async def test_advertises_range_support(self, streamable_track, client):
        r = client.get(f"/api/v1/tracks/{streamable_track.id}/stream")
        assert r.headers.get("accept-ranges") == "bytes"


class TestRanges:
    @pytest.mark.asyncio
    async def test_closed_range(self, streamable_track, client):
        r = client.get(f"/api/v1/tracks/{streamable_track.id}/stream",
                       headers={"Range": "bytes=0-99"})
        assert r.status_code == 206
        assert r.content == CONTENT[0:100]
        assert r.headers["content-range"] == f"bytes 0-99/{CONTENT_LEN}"
        assert int(r.headers["content-length"]) == 100

    @pytest.mark.asyncio
    async def test_mid_file_range(self, streamable_track, client):
        r = client.get(f"/api/v1/tracks/{streamable_track.id}/stream",
                       headers={"Range": "bytes=1000-1999"})
        assert r.status_code == 206
        assert r.content == CONTENT[1000:2000]

    @pytest.mark.asyncio
    async def test_open_ended_range_runs_to_eof(self, streamable_track, client):
        start = CONTENT_LEN - 500
        r = client.get(f"/api/v1/tracks/{streamable_track.id}/stream",
                       headers={"Range": f"bytes={start}-"})
        assert r.status_code == 206
        assert r.content == CONTENT[start:]

    @pytest.mark.asyncio
    async def test_suffix_range_returns_the_LAST_bytes(self, streamable_track, client):
        """`bytes=-100` means the final 100 bytes (RFC 9110 §14.1.2).

        The hand-rolled parser splits on '-', sees an empty first field, and serves
        bytes 0-100 instead — the wrong end of the file, with a Content-Range that
        contradicts the request. Demuxers use suffix ranges to read trailers, so this
        hands them the wrong data while reporting success.
        """
        r = client.get(f"/api/v1/tracks/{streamable_track.id}/stream",
                       headers={"Range": "bytes=-100"})
        assert r.status_code == 206
        assert r.content == CONTENT[-100:]

    @pytest.mark.asyncio
    async def test_unsatisfiable_range_is_416(self, streamable_track, client):
        """A range starting past EOF must be 416, not a clamped 206.

        The hand-rolled version clamps start/end into the file and returns a bogus
        single-byte 206, so a client seeking past the end is told it succeeded.
        """
        r = client.get(f"/api/v1/tracks/{streamable_track.id}/stream",
                       headers={"Range": f"bytes={CONTENT_LEN + 5000}-"})
        assert r.status_code == 416

    @pytest.mark.asyncio
    async def test_multiple_ranges_do_not_500(self, streamable_track, client):
        """`int("100,200")` raises ValueError in the hand-rolled parser."""
        r = client.get(f"/api/v1/tracks/{streamable_track.id}/stream",
                       headers={"Range": "bytes=0-10,20-30"})
        assert r.status_code in (206, 416)
        assert r.status_code != 500

    @pytest.mark.asyncio
    async def test_malformed_range_does_not_500(self, streamable_track, client):
        r = client.get(f"/api/v1/tracks/{streamable_track.id}/stream",
                       headers={"Range": "bytes=abc-def"})
        assert r.status_code != 500


class TestValidators:
    @pytest.mark.asyncio
    async def test_sends_cache_validators(self, streamable_track, client):
        """Without ETag or Last-Modified the browser cannot revalidate.

        Combined with `Cache-Control: private, max-age=3600` that means a blind refetch
        is the only option — it cannot resume or confirm what it already holds.
        """
        r = client.get(f"/api/v1/tracks/{streamable_track.id}/stream")
        assert "etag" in r.headers or "last-modified" in r.headers

    @pytest.mark.asyncio
    async def test_preserves_cache_control(self, streamable_track, client):
        r = client.get(f"/api/v1/tracks/{streamable_track.id}/stream")
        assert "private" in r.headers.get("cache-control", "")

    @pytest.mark.asyncio
    async def test_preserves_audio_media_type(self, streamable_track, client):
        r = client.get(f"/api/v1/tracks/{streamable_track.id}/stream")
        assert r.headers["content-type"].startswith("audio/")


class TestBodyIntegrity:
    @pytest.mark.asyncio
    async def test_body_length_always_matches_declared_length(self, streamable_track, client):
        """The failure mode behind issue #13.

        The hand-rolled generator swallows OSError and breaks on a short read *after*
        the response has already declared Content-Length. The body then ends early with
        a header claiming otherwise, which a demuxer cannot distinguish from corruption
        — it surfaces as PIPELINE_ERROR_READ rather than a clean error.
        """
        for header in (None, "bytes=0-99", "bytes=500-", "bytes=-100"):
            headers = {"Range": header} if header else {}
            r = client.get(f"/api/v1/tracks/{streamable_track.id}/stream", headers=headers)
            if r.status_code in (200, 206):
                assert len(r.content) == int(r.headers["content-length"]), (
                    f"body/Content-Length mismatch for Range={header!r}"
                )

    @pytest.mark.asyncio
    async def test_ranges_reassemble_into_the_original(self, streamable_track, client):
        """Fetch the file in chunks the way a media element does, and rebuild it."""
        chunk = 4096
        rebuilt = b""
        for start in range(0, CONTENT_LEN, chunk):
            end = min(start + chunk - 1, CONTENT_LEN - 1)
            r = client.get(f"/api/v1/tracks/{streamable_track.id}/stream",
                           headers={"Range": f"bytes={start}-{end}"})
            assert r.status_code == 206
            rebuilt += r.content
        assert rebuilt == CONTENT


class TestMissing:
    @pytest.mark.asyncio
    async def test_missing_file_is_404_not_500(self, async_db, client):
        track = await insert_test_track(async_db, title="Gone",
                                        file_path="/nonexistent/definitely/not/here.mp3")
        await async_db.commit()
        r = client.get(f"/api/v1/tracks/{track.id}/stream")
        assert r.status_code == 404
