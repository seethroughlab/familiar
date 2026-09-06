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


class TestTheEmbeddingVersionDocumentsItself:
    """`EMBEDDING_VERSION` is a number whose meaning lives entirely in a comment.

    Every other component of a vector's identity is now carried by
    `clapback_embed.PIPELINE_VERSION`, which is composed from the code that computes
    it and cannot drift. This one is still maintained by hand, and v8 is the first
    bump that does **not** mean "the vectors moved" — it triggers a recompute so the
    corpus can be told what produced them (clapback's `ADR-0006` phase 3). A future
    reader who finds v7 and v8 vectors identical needs the comment to know that was
    intended, so an undocumented bump is a real defect rather than untidiness.
    """

    def _history(self) -> str:
        source = (
            Path(__file__).resolve().parents[1] / "app/config.py"
        ).read_text()
        start = source.index("# Embedding history:")
        return source[start : source.index("EMBEDDING_VERSION = ", start)]

    def test_the_current_version_has_a_history_entry(self):
        assert f"#   v{EMBEDDING_VERSION}:" in self._history()

    def test_the_bump_that_moves_no_vectors_says_so(self):
        """The constant's own rule is "bump when vectors move by more than ~1e-6".
        v8 breaks that rule deliberately, and a deliberate exception that is not
        written down is indistinguishable from a mistake."""
        history = self._history()
        assert "ADR-0006" in history, "the reason for the v8 bump is not recorded"
        assert "do not change" in history or "does not mean" in history


class TestALookupOnlyAcceptsItsOwnPipeline:
    """clapback's `ADR-0006` phase 4 made `pipeline_version` half the corpus key, so
    a recording can hold one vector per pipeline.

    The failure this guards is silent and permanent. A vector from another pipeline
    is a well-formed 512-dimensional unit vector that simply means something else;
    accepted, it would be stored as the track's embedding and compared against
    everything in the library, and nothing downstream could tell.
    """

    IDENTITY = "laion/clap-htsat-unfused+frontend1+artifact1+pool1+fp32"

    def _lookup(self, *, returns: dict, declared: str | None = "unset") -> tuple:
        """Returns `(params_sent, result)`."""
        service = CommunityCacheService(cache_url="http://cache")
        sent: dict = {}

        async def fake(method, url, **kwargs):
            sent.update(kwargs.get("params", {}))

            class Response:
                status_code = 200

                def json(self):
                    return returns

            return Response()

        kw = {} if declared == "unset" else {"pipeline_version": declared}
        with patch.object(service, "_request_with_retry", new=AsyncMock(side_effect=fake)):
            with patch.object(analysis, "_embedder_available", True):
                module = types.ModuleType("clapback_embed")
                module.PIPELINE_VERSION = self.IDENTITY
                with patch.dict(sys.modules, {"clapback_embed": module}):
                    result = asyncio.run(service.lookup("fp", **kw))
        return sent, result

    def _hit(self, pipeline: str | None) -> dict:
        body = {
            "embedding": _vector(),
            "analysis_version": EMBEDDING_VERSION,
            "clap_model_version": CLAP_MODEL_VERSION,
            "contributor_count": 1,
        }
        if pipeline is not None:
            body["pipeline_version"] = pipeline
        return body

    def test_the_request_names_the_pipeline_this_install_runs(self):
        sent, _ = self._lookup(returns=self._hit(self.IDENTITY))
        assert sent["pipeline_version"] == self.IDENTITY

    def test_a_matching_vector_is_accepted(self):
        _, result = self._lookup(returns=self._hit(self.IDENTITY))
        assert result is not None
        assert result.pipeline_version == self.IDENTITY

    def test_a_vector_from_another_pipeline_is_refused(self):
        """**The point of the class.** A corpus predating phase 4 ignores the
        parameter and answers on metadata alone, so a correct request does not make
        the response right — the answer has to be checked, not assumed."""
        _, result = self._lookup(returns=self._hit("something+else+entirely"))
        assert result is None

    def test_an_undeclared_vector_is_still_accepted(self):
        """An older corpus declares nothing. Refusing those would turn every lookup
        against one into a miss, which breaks a client against a server that is
        merely older rather than wrong."""
        _, result = self._lookup(returns=self._hit(None))
        assert result is not None

    def test_an_install_without_an_embedder_sends_nothing(self):
        """It has no pipeline of its own to match against, and an empty parameter
        would be a filter on the empty string."""
        service = CommunityCacheService(cache_url="http://cache")
        sent: dict = {}

        async def fake(method, url, **kwargs):
            sent.update(kwargs.get("params", {}))

            class Response:
                status_code = 404

                def json(self):
                    return {}

            return Response()

        with patch.object(service, "_request_with_retry", new=AsyncMock(side_effect=fake)):
            with patch.object(analysis, "_embedder_available", False):
                assert asyncio.run(service.lookup("fp")) is None
        assert "pipeline_version" not in sent
        assert sent["analysis_version"] == EMBEDDING_VERSION
