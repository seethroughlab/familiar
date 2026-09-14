"""`/tracks/{id}/stream?format=aac` — a phone downloads lossless tracks as AAC (ADR-0118).

These drive the real endpoint with real files that ffmpeg made, because the property under test
is what comes *out*: an MP4 with `ftyp` where the source was FLAC, and the source's own bytes where
it was not. The second is the one to guard hardest — a refactor that re-encodes lossy files would
pass every "is it AAC?" assertion and quietly degrade half the library.

Skipped without ffmpeg, like `test_flac_remux.py`; the lossy pass-through cases do not need it but
share the file for the reader's sake.
"""

import asyncio
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.api.concurrency import EncoderLimiter
from app.services import flac_remux
from tests.factories import insert_test_track

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not available",
)

CACHE_DIR = Path("data/transcode_cache")


def _generate(path: Path, *codec_args: str) -> None:
    """One second of a sine, in whatever ffmpeg is told to write."""
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", *codec_args, str(path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    assert path.exists() and path.stat().st_size > 0


@pytest.fixture()
def flac_file():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "lossless.flac"
        _generate(p, "-c:a", "flac")
        yield p


@pytest.fixture()
def aiff_file():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "lossless.aiff"
        _generate(p, "-c:a", "pcm_s16be")
        yield p


@pytest.fixture()
def alac_file():
    """Lossless in the same container as AAC — the case a suffix check gets wrong."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "lossless.m4a"
        _generate(p, "-c:a", "alac")
        yield p


@pytest.fixture()
def mp3_file():
    """Not a real MP3 — deliberately. The lossy branch must never hand these bytes to ffmpeg, and
    ffmpeg would reject them; so if this ever reaches an encoder, the test fails loudly."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "lossy.mp3"
        p.write_bytes(bytes(range(256)) * 64)
        yield p


async def _track(async_db, path: Path, codec: str | None = None):
    track = await insert_test_track(
        async_db, title=path.stem, file_path=str(path), format=path.suffix.lstrip(".")
    )
    track.codec = codec
    await async_db.commit()
    return track


@pytest.fixture(autouse=True)
def _clean_cache():
    """Track ids are fresh per test, but the cache is a real directory and would otherwise grow."""
    before = set(CACHE_DIR.glob("*")) if CACHE_DIR.exists() else set()
    yield
    if CACHE_DIR.exists():
        for f in set(CACHE_DIR.glob("*")) - before:
            f.unlink(missing_ok=True)


def _is_mp4(body: bytes) -> bool:
    return body[4:8] == b"ftyp"


class TestLosslessIsEncoded:
    @pytest.mark.asyncio
    async def test_flac_becomes_aac_in_mp4(self, async_db, client, flac_file):
        track = await _track(async_db, flac_file, codec="flac")
        r = client.get(f"/api/v1/tracks/{track.id}/stream?format=aac")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("audio/mp4")
        assert _is_mp4(r.content)
        assert len(r.content) < flac_file.stat().st_size
        assert int(r.headers["content-length"]) == len(r.content)

    @pytest.mark.asyncio
    async def test_aiff_goes_straight_to_aac_not_via_flac(self, async_db, client, aiff_file):
        """The AAC branch sits above the browser remux, so this is one encode, not two."""
        track = await _track(async_db, aiff_file, codec="pcm_s16be")
        r = client.get(f"/api/v1/tracks/{track.id}/stream?format=aac")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("audio/mp4")
        assert _is_mp4(r.content)
        assert not (CACHE_DIR / f"{track.id}.flac").exists()

    @pytest.mark.asyncio
    async def test_alac_in_m4a_is_encoded_because_the_codec_says_so(self, async_db, client, alac_file):
        """`.m4a` is the suffix of both ALAC and AAC; only the codec column tells them apart."""
        track = await _track(async_db, alac_file, codec="alac")
        r = client.get(f"/api/v1/tracks/{track.id}/stream?format=aac")
        assert r.status_code == 200
        assert _is_mp4(r.content)
        assert r.content != alac_file.read_bytes()
        assert len(r.content) < alac_file.stat().st_size

    @pytest.mark.asyncio
    async def test_without_the_parameter_a_flac_is_still_a_flac(self, async_db, client, flac_file):
        """No existing client changes behaviour by upgrading the server (point 1)."""
        track = await _track(async_db, flac_file, codec="flac")
        r = client.get(f"/api/v1/tracks/{track.id}/stream")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("audio/flac")
        assert r.content == flac_file.read_bytes()


class TestLossyIsUntouched:
    """Point 2. The parameter means "no larger than AAC", never "re-encode"."""

    @pytest.mark.asyncio
    async def test_mp3_is_served_byte_for_byte(self, async_db, client, mp3_file):
        track = await _track(async_db, mp3_file, codec="mp3")
        plain = client.get(f"/api/v1/tracks/{track.id}/stream")
        asked = client.get(f"/api/v1/tracks/{track.id}/stream?format=aac")
        assert asked.status_code == 200
        assert asked.content == plain.content == mp3_file.read_bytes()
        assert asked.headers["content-type"] == plain.headers["content-type"]
        assert asked.headers["content-type"].startswith("audio/mpeg")

    @pytest.mark.asyncio
    async def test_a_lossy_source_never_reaches_the_encoder(self, async_db, client, mp3_file):
        track = await _track(async_db, mp3_file, codec="mp3")
        with patch.object(flac_remux, "transcode_to_file", new_callable=AsyncMock) as enc, \
             patch("app.api.routes.tracks.streaming.transcode_to_file", enc):
            r = client.get(f"/api/v1/tracks/{track.id}/stream?format=aac")
        assert r.status_code == 200
        enc.assert_not_called()

    @pytest.mark.asyncio
    async def test_aac_in_m4a_is_not_re_encoded(self, async_db, client):
        """Same suffix as the ALAC case above, opposite answer, because the codec differs."""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "lossy.m4a"
            _generate(p, "-c:a", "aac", "-b:a", "96k")
            track = await _track(async_db, p, codec="aac")
            r = client.get(f"/api/v1/tracks/{track.id}/stream?format=aac")
            assert r.status_code == 200
            assert r.content == p.read_bytes()


class TestTheParameter:
    @pytest.mark.asyncio
    async def test_an_unknown_format_is_422_not_a_fallback(self, async_db, client, flac_file):
        track = await _track(async_db, flac_file, codec="flac")
        r = client.get(f"/api/v1/tracks/{track.id}/stream?format=ogg")
        assert r.status_code == 422


class TestTheCache:
    @pytest.mark.asyncio
    async def test_the_second_request_does_not_encode_again(self, async_db, client, flac_file):
        track = await _track(async_db, flac_file, codec="flac")
        first = client.get(f"/api/v1/tracks/{track.id}/stream?format=aac")
        assert first.status_code == 200
        with patch("app.api.routes.tracks.streaming.transcode_to_file", new_callable=AsyncMock) as enc:
            second = client.get(f"/api/v1/tracks/{track.id}/stream?format=aac")
        assert second.status_code == 200
        enc.assert_not_called()
        assert second.content == first.content

    @pytest.mark.asyncio
    async def test_a_newer_source_is_encoded_again(self, async_db, client, flac_file):
        track = await _track(async_db, flac_file, codec="flac")
        assert client.get(f"/api/v1/tracks/{track.id}/stream?format=aac").status_code == 200
        # Retagged, replaced, whatever — the source is newer than the cache.
        future = time.time() + 60
        os.utime(flac_file, (future, future))
        real = flac_remux.transcode_to_file
        with patch("app.api.routes.tracks.streaming.transcode_to_file", side_effect=real) as enc:
            r = client.get(f"/api/v1/tracks/{track.id}/stream?format=aac")
        assert r.status_code == 200
        assert enc.call_count == 1

    @pytest.mark.asyncio
    async def test_the_aac_and_flac_caches_are_different_files(self, async_db, client, aiff_file):
        """Playback still remuxes AIFF to FLAC; a download encodes it to AAC. Two entries, one track."""
        track = await _track(async_db, aiff_file, codec="pcm_s16be")
        assert client.get(f"/api/v1/tracks/{track.id}/stream").headers["content-type"].startswith("audio/flac")
        assert client.get(f"/api/v1/tracks/{track.id}/stream?format=aac").headers["content-type"].startswith("audio/mp4")
        assert (CACHE_DIR / f"{track.id}.flac").exists()
        assert (CACHE_DIR / f"{track.id}.aac.m4a").exists()


class TestRangesOnTheEncode:
    @pytest.mark.asyncio
    async def test_a_range_request_on_a_cached_aac_is_206(self, async_db, client, flac_file):
        """`+faststart` is there so this works: the phone's download resumes by Range."""
        track = await _track(async_db, flac_file, codec="flac")
        whole = client.get(f"/api/v1/tracks/{track.id}/stream?format=aac").content
        r = client.get(f"/api/v1/tracks/{track.id}/stream?format=aac", headers={"Range": "bytes=0-99"})
        assert r.status_code == 206
        assert r.headers["content-range"] == f"bytes 0-99/{len(whole)}"
        assert r.content == whole[:100]


class TestTheEncoderBound:
    @pytest.mark.asyncio
    async def test_at_most_limit_encodes_run_at_once_and_the_rest_wait(self):
        limiter = EncoderLimiter(limit=4)
        running = 0
        peak = 0

        async def encode():
            nonlocal running, peak
            await limiter.acquire()
            try:
                running += 1
                peak = max(peak, running)
                await asyncio.sleep(0.01)
                running -= 1
            finally:
                limiter.release()

        await asyncio.gather(*(encode() for _ in range(10)))
        assert peak == 4
        assert limiter.peak_in_flight == 4
        assert limiter.waited >= 6
        assert limiter.in_flight == 0

    @pytest.mark.asyncio
    async def test_the_route_encodes_under_the_bound(self, async_db, client, flac_file):
        from app.api.routes.tracks import streaming

        track = await _track(async_db, flac_file, codec="flac")
        before = streaming.encoder_limiter.peak_in_flight
        assert client.get(f"/api/v1/tracks/{track.id}/stream?format=aac").status_code == 200
        assert streaming.encoder_limiter.peak_in_flight >= max(before, 1)
        assert streaming.encoder_limiter.in_flight == 0

    @pytest.mark.asyncio
    async def test_a_failed_encode_gives_the_slot_back(self, async_db, client, flac_file):
        """A slot taken and never returned ratchets the bound to zero, silently — ADR-0112 point 5's
        failure, one resource over."""
        from app.api.routes.tracks import streaming

        track = await _track(async_db, flac_file, codec="flac")
        with patch(
            "app.api.routes.tracks.streaming.transcode_to_file",
            new_callable=AsyncMock,
            side_effect=RuntimeError("ffmpeg said no"),
        ):
            r = client.get(f"/api/v1/tracks/{track.id}/stream?format=aac")
        assert r.status_code == 502
        assert streaming.encoder_limiter.in_flight == 0
