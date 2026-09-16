"""The corpus is asked by recording before it is asked by hash (ADR-0119).

clapback's `ADR-0019` measured the corpus key as a function of the fingerprinting
path — `fpcalc` and pyacoustid agree on 24 of 56 FLACs — so a miss by hash does not
mean the corpus lacks the recording. The rule became: look up by recording if you hold
an id, by hash otherwise, contribute under your hash either way.

Four properties, each the corpus's rather than Familiar's:

**The id is asked first, and the hash only on a 404.** Asked the other way round, the
recording request would only ever run for tracks this installation has *not*
contributed, which are exactly the untagged arrivals that hold no id.

**Unanswered is not a miss.** A recording request that could not be completed does not
fall through to the hash: that would turn "the server did not answer" into "no row
under our key", and on the contribute path into a duplicate submission — the
manufactured agreement clapback's `ADR-0008` exists to avoid.

**The row's own key is kept.** After a recording hit the row may be another path's; a
caller can tell, and `embedding_source` records which door answered.

**A contribution carries the id when it is held.** A claim in the same request, so
`ADR-0019` point 2's per-recording agreement runs at write time.

Free of `numpy`, `librosa` and the ONNX artifacts, like the rest of the suite that
touches this path — the transport is what is under test, not the encoder.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.services.community_cache import (
    CommunityCacheService,
    CommunityCacheUnavailable,
)

PIPELINE = "laion/clap-htsat-unfused+frontend1+artifact1+pool1+fp32"
MBID = "6f8b5d1a-2c3e-4f5a-9b7c-1d2e3f4a5b6c"


def _vector() -> list[float]:
    return [((i * 7919) % 1000 + 1) / 31337.0 for i in range(512)]


class _Response:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def _row(fingerprint_hash: str, pipeline: str = PIPELINE, contributors: int = 1) -> dict:
    return {
        "fingerprint_hash": fingerprint_hash,
        "pipeline_version": pipeline,
        "embedding": _vector(),
        "contributor_count": contributors,
        "analysis_version": 8,
        "clap_model_version": "laion/clap-htsat-unfused",
        "recording_claims": 2,
    }


def _run(service: CommunityCacheService, answers: dict[str, object], **kwargs):
    """Drive `lookup` against a transport that answers by URL suffix.

    `answers` maps a substring of the URL to a `_Response` or to `None` (the request
    could not be completed). Returns `(result, [urls requested in order])`.
    """
    calls: list[tuple[str, dict]] = []

    async def fake(method, url, **call_kwargs):
        calls.append((url, call_kwargs.get("params", {})))
        for needle, answer in answers.items():
            if needle in url:
                return answer
        raise AssertionError(f"unexpected request: {url}")

    with patch.object(service, "_request_with_retry", new=AsyncMock(side_effect=fake)):
        result = asyncio.run(service.lookup("fp", pipeline_version=PIPELINE, **kwargs))
    return result, calls


class TestTheRecordingIsAskedFirst:
    def test_a_hit_by_recording_makes_no_hash_request(self):
        service = CommunityCacheService(cache_url="http://cache")
        result, calls = _run(
            service,
            {"/v1/recordings/": _Response(200, {"embeddings": [_row("other-path-key")]})},
            recording_mbid=MBID,
        )
        assert result is not None
        assert [url for url, _ in calls] == [f"http://cache/v1/recordings/{MBID}"]

    def test_the_request_names_the_claim_type_and_the_pipeline(self):
        """`type` because the endpoint also serves AcoustID ids (`ADR-0019` point 6);
        `pipeline_version` because a vector from another pipeline is a wrong answer
        wearing the right shape."""
        service = CommunityCacheService(cache_url="http://cache")
        _, calls = _run(
            service,
            {"/v1/recordings/": _Response(200, {"embeddings": [_row("k")]})},
            recording_mbid=MBID,
        )
        _, params = calls[0]
        assert params["type"] == "musicbrainz_recording"
        assert params["pipeline_version"] == PIPELINE

    def test_the_first_row_is_taken(self):
        """The server orders by claims, then contributors; the first is the answer,
        as `clapback-client` takes it."""
        service = CommunityCacheService(cache_url="http://cache")
        result, _ = _run(
            service,
            {
                "/v1/recordings/": _Response(
                    200, {"embeddings": [_row("first", contributors=3), _row("second")]}
                )
            },
            recording_mbid=MBID,
        )
        assert result is not None
        assert result.fingerprint_hash == "first"
        assert result.contributor_count == 3

    def test_without_an_id_only_the_hash_is_asked(self):
        service = CommunityCacheService(cache_url="http://cache")
        result, calls = _run(service, {"/v1/embeddings/": _Response(200, _row("ours"))})
        assert result is not None
        assert len(calls) == 1
        assert "/v1/embeddings/" in calls[0][0]


class TestTheHashIsTheFallback:
    def test_a_404_by_recording_falls_through_to_the_hash(self):
        """Nothing claimed under the id yet — our own row, contributed before the
        backfill named it, may still be there under our key."""
        service = CommunityCacheService(cache_url="http://cache")
        result, calls = _run(
            service,
            {
                "/v1/recordings/": _Response(404),
                "/v1/embeddings/": _Response(200, _row("ours")),
            },
            recording_mbid=MBID,
        )
        assert result is not None
        assert result.via == "hash"
        assert [("recordings" in url) for url, _ in calls] == [True, False]

    def test_an_empty_row_list_is_a_miss_too(self):
        service = CommunityCacheService(cache_url="http://cache")
        result, calls = _run(
            service,
            {
                "/v1/recordings/": _Response(200, {"embeddings": []}),
                "/v1/embeddings/": _Response(404),
            },
            recording_mbid=MBID,
        )
        assert result is None
        assert len(calls) == 2

    def test_a_row_from_another_pipeline_is_not_an_answer(self):
        """The filter was sent; the response is checked anyway, as the hash path
        checks it (clapback's `ADR-0006`). It falls through: the hash row is filtered
        the same way and may be ours."""
        service = CommunityCacheService(cache_url="http://cache")
        result, calls = _run(
            service,
            {
                "/v1/recordings/": _Response(
                    200, {"embeddings": [_row("theirs", pipeline="something+else")]}
                ),
                "/v1/embeddings/": _Response(404),
            },
            recording_mbid=MBID,
        )
        assert result is None
        assert len(calls) == 2


class TestUnansweredIsNotAMiss:
    """ADR-0119 point 4. The transport returns `None` when a request could not be
    completed — rate-limited past its retries, timed out, unreachable."""

    def test_it_does_not_fall_through_to_the_hash(self):
        service = CommunityCacheService(cache_url="http://cache")
        result, calls = _run(
            service,
            {"/v1/recordings/": None, "/v1/embeddings/": _Response(200, _row("ours"))},
            recording_mbid=MBID,
        )
        assert result is None
        assert len(calls) == 1, (
            "an unanswered recording request must not be followed by a hash request"
        )

    def test_it_raises_when_the_caller_asked_to_know(self):
        service = CommunityCacheService(cache_url="http://cache")
        with pytest.raises(CommunityCacheUnavailable):
            _run(service, {"/v1/recordings/": None}, recording_mbid=MBID, raise_on_error=True)

    def test_a_server_error_is_treated_the_same_way(self):
        service = CommunityCacheService(cache_url="http://cache")
        result, calls = _run(
            service,
            {"/v1/recordings/": _Response(503), "/v1/embeddings/": _Response(200, _row("ours"))},
            recording_mbid=MBID,
        )
        assert result is None
        assert len(calls) == 1


class TestTheRowsOwnKeyIsKept:
    def test_a_cross_path_hit_says_so(self):
        service = CommunityCacheService(cache_url="http://cache")
        result, _ = _run(
            service,
            {"/v1/recordings/": _Response(200, {"embeddings": [_row("pyacoustid-key")]})},
            recording_mbid=MBID,
        )
        assert result is not None
        assert result.via == "recording"
        assert result.fingerprint_hash == "pyacoustid-key"
        assert result.fingerprint_hash != service.hash_fingerprint("fp")

    def test_a_hash_hit_carries_our_key(self):
        service = CommunityCacheService(cache_url="http://cache")
        result, _ = _run(service, {"/v1/embeddings/": _Response(200, _row("ignored"))})
        assert result is not None
        assert result.via == "hash"
        assert result.fingerprint_hash == service.hash_fingerprint("fp")


class TestTheContributionCarriesTheId:
    def _sent(self, **kwargs) -> dict:
        sent: dict = {}

        async def fake(method, url, **call_kwargs):
            sent.update(call_kwargs.get("json", {}))
            return _Response(201, {"status": "created", "contributor_count": 1})

        service = CommunityCacheService(cache_url="http://cache", client_id="install-a")
        with patch.object(service, "_request_with_retry", new=AsyncMock(side_effect=fake)):
            asyncio.run(service.contribute("fp", _vector(), pipeline_version=PIPELINE, **kwargs))
        return sent

    def test_it_is_sent_when_the_caller_holds_one(self):
        assert self._sent(recording_mbid=MBID)["recording_mbid"] == MBID

    def test_it_is_absent_rather_than_null_when_not_held(self):
        """A claim is an assertion; an empty one would be a false one."""
        assert "recording_mbid" not in self._sent()


class TestTheAnalysisPipelinePassesWhatItHolds:
    """A property of the caller, which a change to the client alone would leave
    unprotected — the same shape `test_community_cache_contribution` uses."""

    def test_the_lookup_and_the_contribution_both_carry_the_id(self):
        source = (
            Path(__file__).resolve().parents[1] / "app/services/tasks/analysis_pipeline.py"
        ).read_text()
        assert "recording_mbid = track.musicbrainz_track_id or None" in source
        assert "lookup(acoustid_fingerprint, recording_mbid=recording_mbid)" in source
        assert "recording_mbid=recording_mbid," in source.split("cache_service.contribute(")[1]

    def test_the_source_records_which_door_answered(self):
        source = (
            Path(__file__).resolve().parents[1] / "app/services/tasks/analysis_pipeline.py"
        ).read_text()
        assert 'embedding_source = f"community_cache:{cached.via}"' in source
