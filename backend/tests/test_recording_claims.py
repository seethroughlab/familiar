"""What this installation sends when it names a recording.

clapback's `ADR-0012`, and the cheap half of this repository's `ADR-0102` point 5.
A claim attaches a MusicBrainz recording id to a row the corpus already holds,
through its own endpoint, so that naming a recording never means re-sending its
vector — a repeat contribution is recorded as agreement, and an installation
must not be made to agree with itself by tagging its library.

Free of the network: the transport is captured, not exercised.
"""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, patch

from app.services.community_cache import CommunityCacheService

MBID = "1c6da765-da50-476b-a000-61e7cf45ded8"


def _service(client_id: str | None = "install-1") -> CommunityCacheService:
    return CommunityCacheService(cache_url="https://corpus.invalid", client_id=client_id)


def _capture(service: CommunityCacheService, status: int = 201) -> tuple[str, str, dict]:
    sent: dict = {}
    seen: dict = {}

    async def fake(method, url, **kw):
        seen["method"], seen["url"] = method, url
        sent.update(kw.get("json", {}))

        class Response:
            status_code = status
            text = ""

        return Response()

    with patch.object(service, "_request_with_retry", new=AsyncMock(side_effect=fake)):
        ok = asyncio.run(service.claim_recording("AQADfingerprint", MBID))
    sent["_ok"] = ok
    return seen.get("method", ""), seen.get("url", ""), sent


class TestTheClaimGoesToItsOwnPath:
    def test_it_posts_to_the_claims_endpoint_not_embeddings(self):
        """The whole reason the endpoint exists."""
        method, url, _ = _capture(_service())
        assert method == "POST"
        assert url.endswith("/v1/recordings/claims")
        assert "/v1/embeddings" not in url

    def test_it_sends_no_vector(self):
        _, _, sent = _capture(_service())
        assert "embedding" not in sent
        assert set(sent) - {"_ok"} == {"fingerprint_hash", "recording_mbid", "client_id"}

    def test_the_hash_is_the_canonical_one(self):
        """`ADR-0114`: hash what chromaprint returned. The claim keys on the same
        hash the contribution did, or it names a row that does not exist."""
        _, _, sent = _capture(_service())
        assert sent["fingerprint_hash"] == CommunityCacheService.hash_fingerprint("AQADfingerprint")


class TestItIsAttributed:
    def test_it_carries_the_installation_id(self):
        _, _, sent = _capture(_service("install-9"))
        assert sent["client_id"] == "install-9"

    def test_without_an_id_it_does_not_send_at_all(self):
        """A claim nobody made can be neither revoked nor counted, and the corpus
        would refuse it anyway. Better to not ask."""
        service = _service(client_id=None)
        with patch.object(service, "_request_with_retry", new=AsyncMock()) as req:
            ok = asyncio.run(service.claim_recording("AQADfp", MBID))
        assert ok is False
        assert req.await_count == 0


class TestWhatTheAnswerMeans:
    def test_created_is_true(self):
        assert _capture(_service(), status=201)[2]["_ok"] is True

    def test_an_absent_row_is_false_not_an_exception(self):
        """404 means contribute the vector first. The script counts it and moves on."""
        assert _capture(_service(), status=404)[2]["_ok"] is False

    def test_the_method_says_never_to_resend_the_vector(self):
        """The one thing a future maintainer must not 'fix'."""
        doc = " ".join((inspect.getdoc(CommunityCacheService.claim_recording) or "").split())
        assert "never re-send the vector" in doc.lower()
