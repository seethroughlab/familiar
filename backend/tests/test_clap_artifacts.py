"""The CLAP encoders reach a server outside the image, and only the right bytes do (ADR-0132 point 8).

No network: downloads go through an `httpx.MockTransport`, and the pinned artifacts are swapped for
small ones whose hashes the test knows.
"""

from __future__ import annotations

import asyncio
import hashlib

import httpx
import pytest

import app.services.clap_artifacts as clap
from app.services.clap_artifacts import Artifact

AUDIO = b"audio encoder bytes"
TEXT = b"text encoder bytes, somewhat longer"


def _artifact(data: bytes) -> Artifact:
    return Artifact(size=len(data), sha256=hashlib.sha256(data).hexdigest())


@pytest.fixture
def fake_artifacts(monkeypatch, tmp_path):
    monkeypatch.setattr(clap, "ARTIFACTS", {"a.onnx": _artifact(AUDIO), "t.onnx": _artifact(TEXT)})
    monkeypatch.setenv("CLAPBACK_MODEL_DIR", str(tmp_path))
    return tmp_path


def _serving(files: dict[str, bytes], seen: list[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        name = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, content=files[name]) if name in files else httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestPresence:
    def test_absent_and_wrong_sized_files_are_missing(self, fake_artifacts):
        (fake_artifacts / "a.onnx").write_bytes(AUDIO[:-1])
        assert clap.missing() == ["a.onnx", "t.onnx"]
        (fake_artifacts / "a.onnx").write_bytes(AUDIO)
        assert clap.missing() == ["t.onnx"]

    def test_verify_reads_the_whole_file(self, fake_artifacts):
        (fake_artifacts / "a.onnx").write_bytes(AUDIO)
        (fake_artifacts / "t.onnx").write_bytes(b"x" * len(TEXT))  # right size, wrong bytes
        assert clap.missing() == []
        [problem] = clap.verify()
        assert problem.startswith("t.onnx: sha256 ")


class TestDownload:
    def test_fetches_from_the_release_matching_the_version(self, fake_artifacts):
        seen: list[str] = []
        client = _serving({"a.onnx": AUDIO, "t.onnx": TEXT}, seen)
        fetched = asyncio.run(clap.download("v0.2.0-beta8", client=client))
        assert fetched == ["a.onnx", "t.onnx"]
        assert seen == [
            "https://github.com/seethroughlab/familiar/releases/download/v0.2.0-beta8/a.onnx",
            "https://github.com/seethroughlab/familiar/releases/download/v0.2.0-beta8/t.onnx",
        ]
        assert clap.verify() == []
        assert not list(fake_artifacts.glob("*.part"))

    def test_only_missing_files_are_fetched(self, fake_artifacts):
        (fake_artifacts / "a.onnx").write_bytes(AUDIO)
        seen: list[str] = []
        asyncio.run(clap.download("v1", client=_serving({"t.onnx": TEXT}, seen)))
        assert [u.rsplit("/", 1)[-1] for u in seen] == ["t.onnx"]

    def test_wrong_bytes_never_become_a_loadable_file(self, fake_artifacts):
        client = _serving({"a.onnx": b"not the encoder", "t.onnx": TEXT}, [])
        with pytest.raises(ValueError, match="a.onnx"):
            asyncio.run(clap.download("v1", client=client))
        assert not (fake_artifacts / "a.onnx").exists()
        assert not list(fake_artifacts.glob("*.part"))

    def test_a_missing_asset_raises(self, fake_artifacts):
        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(clap.download("v1", client=_serving({}, [])))


class TestStartup:
    def test_a_dev_server_does_not_try_to_download(self, fake_artifacts, monkeypatch):
        monkeypatch.setattr(clap, "get_app_version", lambda: "dev")
        called = []

        async def download(tag, directory=None, *, client=None):
            called.append(tag)
            return []

        monkeypatch.setattr(clap, "download", download)
        asyncio.run(clap.ensure_present())
        assert called == []

    def test_a_released_server_fetches_its_own_version(self, fake_artifacts, monkeypatch):
        monkeypatch.setattr(clap, "get_app_version", lambda: "v0.2.0-beta8")
        called = []

        async def download(tag, directory=None, *, client=None):
            called.append(tag)
            return []

        monkeypatch.setattr(clap, "download", download)
        asyncio.run(clap.ensure_present())
        assert called == ["v0.2.0-beta8"]

    def test_a_failed_download_does_not_raise(self, fake_artifacts, monkeypatch):
        monkeypatch.setattr(clap, "get_app_version", lambda: "v1")

        async def download(tag, directory=None, *, client=None):
            raise httpx.ConnectError("offline")

        monkeypatch.setattr(clap, "download", download)
        asyncio.run(clap.ensure_present())  # logged, embeddings stay off

    def test_the_image_setting_wins(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CLAPBACK_MODEL_DIR", "/app/models/clapback")
        assert str(clap.configure_model_dir()) == "/app/models/clapback"

    def test_otherwise_the_encoders_live_in_the_data_dir(self, monkeypatch):
        monkeypatch.delenv("CLAPBACK_MODEL_DIR", raising=False)
        path = clap.configure_model_dir()
        assert path == clap.settings.models_dir / "clapback"
        # Set for the embedder and every pool spawned after it.
        import os

        assert os.environ["CLAPBACK_MODEL_DIR"] == str(path)


class TestVerifyCommand:
    def test_exits_nonzero_on_a_mismatch(self, fake_artifacts, capsys):
        (fake_artifacts / "a.onnx").write_bytes(AUDIO)
        assert clap.main(["verify", str(fake_artifacts)]) == 1
        assert "t.onnx: not found" in capsys.readouterr().out

    def test_exits_zero_when_every_file_matches(self, fake_artifacts):
        (fake_artifacts / "a.onnx").write_bytes(AUDIO)
        (fake_artifacts / "t.onnx").write_bytes(TEXT)
        assert clap.main(["verify", str(fake_artifacts)]) == 0


def test_the_pinned_names_are_the_files_the_embedder_loads():
    artifacts = pytest.importorskip("clapback_embed.artifacts")
    assert set(clap.ARTIFACTS) == {artifacts.AUDIO_FP32, artifacts.TEXT_FP32}
