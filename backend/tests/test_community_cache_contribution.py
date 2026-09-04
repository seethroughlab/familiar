"""What this installation sends when it contributes an embedding.

Two properties, both of them the corpus's rather than Familiar's, and neither
previously covered by anything:

**The vector goes as computed.** Contribution used to round to float16 to halve the
request body. That cost 2.1e-08 of cosine distance — inside clapback's `identical`
band, so nothing was broken, but about a hundred million times the 3.3e-16 that its
float4 storage costs, and written down nowhere. clapback's `ADR-0002` point 3 makes
stored precision part of the corpus contract; contributed precision should not be
quietly worse than what the corpus can hold.

**A contribution carries an installation identifier.** clapback's `ADR-0004`: without
one a submission is still accepted and still stored, but can never count toward
independent agreement, because nothing can show it came from a different party. It is
self-issued, needs no registration, and identifies an installation rather than a
person.

Free of `numpy`, `librosa` and the ONNX artifacts, like the rest of the suite that
touches this path — the transport is what is under test, not the encoder.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.services.app_settings import AppSettingsService
from app.services.community_cache import (
    CommunityCacheService,
    get_community_cache_service,
)


def _vector() -> list[float]:
    """512 values that float16 cannot hold exactly, so a rounding regression shows up."""
    return [((i * 7919) % 1000 + 1) / 31337.0 for i in range(512)]


def _capture(service: CommunityCacheService, fingerprint: str = "fp") -> dict:
    sent: dict = {}

    async def fake(method, url, **kwargs):
        sent.update(kwargs.get("json", {}))

        class Response:
            status_code = 201

            def json(self):
                return {"status": "created", "contributor_count": 1}

        return Response()

    with patch.object(service, "_request_with_retry", new=AsyncMock(side_effect=fake)):
        asyncio.run(service.contribute(fingerprint, _vector()))
    return sent


class TestTheVectorIsSentAsComputed:
    def test_no_component_is_rounded(self):
        sent = _capture(CommunityCacheService(cache_url="http://cache"))
        assert sent["embedding"] == _vector()

    def test_the_payload_survives_a_json_round_trip(self):
        """The wire format must not be where the precision goes."""
        sent = _capture(CommunityCacheService(cache_url="http://cache"))
        assert json.loads(json.dumps(sent))["embedding"] == _vector()


class TestTheContributionIsAttributed:
    def test_client_id_is_sent_when_known(self):
        sent = _capture(CommunityCacheService(cache_url="http://cache", client_id="install-a"))
        assert sent["client_id"] == "install-a"

    def test_the_field_is_absent_rather_than_null_when_unknown(self):
        """`ADR-0004` point 3 — accepted without one. A null would be a claim, not a silence."""
        sent = _capture(CommunityCacheService(cache_url="http://cache"))
        assert "client_id" not in sent


class TestTheIdentifierIsStable:
    def test_it_is_generated_once_and_reused(self, tmp_path: Path):
        service = AppSettingsService(settings_path=tmp_path / "settings.json")
        assert service.get().community_cache_client_id == ""
        first = service.ensure_community_cache_client_id()
        assert first
        assert service.ensure_community_cache_client_id() == first

    def test_it_survives_a_restart(self, tmp_path: Path):
        path = tmp_path / "settings.json"
        first = AppSettingsService(settings_path=path).ensure_community_cache_client_id()
        assert AppSettingsService(settings_path=path).ensure_community_cache_client_id() == first

    def test_it_is_written_to_the_settings_file(self, tmp_path: Path):
        path = tmp_path / "settings.json"
        generated = AppSettingsService(settings_path=path).ensure_community_cache_client_id()
        assert json.loads(path.read_text())["community_cache_client_id"] == generated


class TestTheSingletonTracksTheIdentity:
    def test_a_new_identifier_rebuilds_the_service(self):
        first = get_community_cache_service(cache_url="http://cache", client_id="install-a")
        second = get_community_cache_service(cache_url="http://cache", client_id="install-b")
        assert second is not first
        assert second.client_id == "install-b"

    def test_a_caller_that_does_not_know_it_does_not_clear_it(self):
        """The features path calls the same factory without one, and must not disarm the embedding path."""
        get_community_cache_service(cache_url="http://cache", client_id="install-a")
        again = get_community_cache_service(cache_url="http://cache")
        assert again.client_id == "install-a"
