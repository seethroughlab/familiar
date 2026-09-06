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

**A contribution declares its pipeline, and only when it can.** clapback's `ADR-0006`
phase 2. `EMBEDDING_VERSION` and the checkpoint together do not establish that two
vectors are comparable; `clapback_embed.PIPELINE_VERSION` does. The property under
test is as much what is *not* sent: this method is handed a vector and does not know
what produced it, so it never fills the field in from whatever embedder happens to be
installed.

Free of `numpy`, `librosa` and the ONNX artifacts, like the rest of the suite that
touches this path — the transport is what is under test, not the encoder.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.config import EMBEDDING_VERSION
from app.services import analysis
from app.services.app_settings import AppSettingsService
from app.services.community_cache import (
    CLAP_MODEL_VERSION,
    CommunityCacheService,
    get_community_cache_service,
)


def _vector() -> list[float]:
    """512 values that float16 cannot hold exactly, so a rounding regression shows up."""
    return [((i * 7919) % 1000 + 1) / 31337.0 for i in range(512)]


def _capture(service: CommunityCacheService, fingerprint: str = "fp", **kwargs) -> dict:
    sent: dict = {}

    async def fake(method, url, **call_kwargs):
        sent.update(call_kwargs.get("json", {}))

        class Response:
            status_code = 201

            def json(self):
                return {"status": "created", "contributor_count": 1}

        return Response()

    with patch.object(service, "_request_with_retry", new=AsyncMock(side_effect=fake)):
        asyncio.run(service.contribute(fingerprint, _vector(), **kwargs))
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


class TestTheContributionDeclaresItsPipeline:
    """clapback's `ADR-0006` phase 2 — the field that says whether two vectors are
    comparable at all."""

    IDENTITY = "laion/clap-htsat-unfused+frontend1+artifact1+pool1+fp32"

    def test_it_is_sent_when_the_caller_knows_it(self):
        sent = _capture(
            CommunityCacheService(cache_url="http://cache"),
            pipeline_version=self.IDENTITY,
        )
        assert sent["pipeline_version"] == self.IDENTITY

    def test_the_field_is_absent_rather_than_null_when_unknown(self):
        """Absent means "unknown", which is true. A null would be a claim about the
        vector that nobody made."""
        sent = _capture(CommunityCacheService(cache_url="http://cache"))
        assert "pipeline_version" not in sent

    def test_it_is_never_inferred_from_the_installed_embedder(self):
        """**The property that matters most here.** `contribute` is handed a vector
        and does not know what computed it. Reading `PIPELINE_VERSION` from whatever
        is installed would declare today's pipeline for a vector computed months ago
        by a different one — on every row of a backfill at once, and asserted rather
        than measured, so nothing afterwards could tell which rows were true."""
        tree = ast.parse(Path(inspect.getfile(CommunityCacheService)).read_text())
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "contribute"
        )
        # The docstring says the word in order to explain the rule, so it is
        # dropped before the body is read.
        body = fn.body[1:] if ast.get_docstring(fn) else fn.body
        code = "\n".join(ast.unparse(n) for n in body)
        assert "clapback_embed" not in code
        assert "PIPELINE_VERSION" not in code

    def test_the_rest_of_the_payload_is_unchanged_by_it(self):
        """Additive. A corpus that predates the field must keep accepting these, and
        the fields it already keys on must arrive exactly as before."""
        sent = _capture(
            CommunityCacheService(cache_url="http://cache", client_id="install-a"),
            pipeline_version=self.IDENTITY,
        )
        assert sent["embedding"] == _vector()
        assert sent["client_id"] == "install-a"
        assert sent["analysis_version"] == EMBEDDING_VERSION
        assert sent["clap_model_version"] == CLAP_MODEL_VERSION


class TestOnlyAFreshlyComputedVectorDeclaresOne:
    """Which call sites may declare a pipeline, and which may not.

    This is a property of the *callers*, not of the client, and it is the half that
    a change to `contribute` alone would leave unprotected."""

    def test_the_analysis_pipeline_declares_it(self):
        """It contributes only in the branch where `extract_embedding` just ran — a
        community-cache hit returns before it — so the installed embedder is provably
        what produced the vector."""
        source = (
            Path(__file__).resolve().parents[1]
            / "app/services/tasks/analysis_pipeline.py"
        ).read_text()
        assert "pipeline_version=embedding_pipeline_version()" in source

    def test_the_backfill_declares_nothing(self):
        """It contributes vectors out of the database, computed at some earlier time
        by an embedder nobody recorded. `embedding_version == 7` narrows that and does
        not pin it."""
        source = (
            Path(__file__).resolve().parents[1]
            / "scripts/backfill_community_cache.py"
        ).read_text()
        call = source[source.index("await cache.contribute(") :]
        call = call[: call.index(")") + 1]
        assert "pipeline_version" not in call


class TestTheAccessorReadsTheLibraryRatherThanAConstant:
    """`PIPELINE_VERSION` written down in `config.py` would be a second copy of a
    fact, maintained by hand — which is what `EMBEDDING_VERSION` already is and why
    `ADR-0006` exists. Read from the encoder that just ran, it cannot drift."""

    def test_it_returns_what_the_installed_embedder_reports(self):
        module = types.ModuleType("clapback_embed")
        module.PIPELINE_VERSION = "checkpoint+frontend9+artifact9+pool9+fp32"
        with patch.dict(sys.modules, {"clapback_embed": module}):
            with patch.object(analysis, "_embedder_available", True):
                assert analysis.embedding_pipeline_version() == module.PIPELINE_VERSION

    def test_it_returns_none_when_the_embedder_is_absent(self):
        """An installation with no embedder computes no vectors, so it has nothing to
        declare — and None means "unknown", which the corpus already handles."""
        with patch.object(analysis, "_embedder_available", False):
            assert analysis.embedding_pipeline_version() is None

    def test_an_older_embedder_without_the_attribute_declares_nothing(self):
        """Silence beats a guess. The corpus reads absent as unknown, which is true;
        a fabricated string would be a claim it cannot check."""
        module = types.ModuleType("clapback_embed")
        with patch.dict(sys.modules, {"clapback_embed": module}):
            with patch.object(analysis, "_embedder_available", True):
                assert analysis.embedding_pipeline_version() is None
