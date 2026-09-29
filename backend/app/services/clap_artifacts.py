"""The CLAP encoder files: where they are, whether they are there, and how a server gets them (ADR-0132 point 8).

The image carries the encoders at `/app/models/clapback`, produced by the Dockerfile's `onnx-export`
stage from the pinned checkpoint. A server outside the image has no export stage, so it downloads
them from the GitHub release matching its own version, and accepts a file only if its SHA-256 is
the one recorded here.

**The hashes can be pinned in source because the export is deterministic.** Measured 2026-09-29
from the published images: `clap_audio.onnx` and `clap_text.onnx` are byte-identical in
v0.2.0-beta6 amd64, v0.2.0-beta7 amd64 and v0.2.0-beta7 arm64. That keeps the Dockerfile's premise,
"reproducible from the pinned checkpoint rather than trusted from a URL": the URL only delivers
bytes, and this file decides whether they are the right ones. `clap_audio_fp16.onnx` is *not*
reproducible (it differs between those releases), which is one reason it is not published. The
other is that nothing here uses it; fp16 vectors may not be contributed.

**A changed hash is a pipeline change, not a nuisance.** The release workflow runs `verify` against
the image it just built, so an export that drifts (the Dockerfile fetches `export_models.py` from
clapback's `main`) fails the release instead of quietly moving every vector. Update these hashes
only together with an `EMBEDDING_VERSION` bump and a re-analysis.

    python -m app.services.clap_artifacts verify [DIR]   # exit 1 unless every file matches
"""

from __future__ import annotations

import hashlib
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from app.config import get_app_version, settings

logger = logging.getLogger(__name__)

RELEASE_ASSET_URL = "https://github.com/seethroughlab/familiar/releases/download/{tag}/{name}"


@dataclass(frozen=True)
class Artifact:
    size: int
    sha256: str


#: The fp32 encoders `clapback_embed` loads. The text encoder is one file: the export writes no
#: `clap_text.onnx.data` at this size, despite that package's docstring allowing for one.
ARTIFACTS: dict[str, Artifact] = {
    "clap_audio.onnx": Artifact(
        size=117_275_257,
        sha256="d60528e65d297e3567c640e010412a2b7197189716de2c3405d4a5fc2995b160",
    ),
    "clap_text.onnx": Artifact(
        size=501_448_656,
        sha256="de08d36f0f84a6b232c5961b91fba7a8586c22e89ad69ed452992bd34b125451",
    ),
}


def model_dir() -> Path:
    """`CLAPBACK_MODEL_DIR` when set (the image sets it), else `data_dir/models/clapback`."""
    override = os.environ.get("CLAPBACK_MODEL_DIR")
    return Path(override).expanduser() if override else settings.models_dir / "clapback"


def configure_model_dir() -> Path:
    """Point `clapback_embed` at `model_dir()`.

    Called at startup, before any analysis pool is spawned, so the children inherit it. Without
    this, `clapback_embed` would look in `~/.cache/clapback/models`, outside the data directory.
    """
    path = model_dir()
    os.environ.setdefault("CLAPBACK_MODEL_DIR", str(path))
    return path


def missing(directory: Path | None = None) -> list[str]:
    """Files absent or of the wrong size. Cheap enough to ask per track: two `stat` calls."""
    directory = directory or model_dir()
    absent = []
    for name, artifact in ARTIFACTS.items():
        path = directory / name
        try:
            if path.stat().st_size != artifact.size:
                absent.append(name)
        except OSError:
            absent.append(name)
    return absent


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(directory: Path | None = None) -> list[str]:
    """Every problem with the files in `directory`, reading each one in full. Empty means valid."""
    directory = directory or model_dir()
    problems = []
    for name, artifact in ARTIFACTS.items():
        path = directory / name
        if not path.is_file():
            problems.append(f"{name}: not found in {directory}")
            continue
        actual = sha256_of(path)
        if actual != artifact.sha256:
            problems.append(f"{name}: sha256 {actual}, expected {artifact.sha256}")
    return problems


async def download(tag: str, directory: Path | None = None, *, client=None) -> list[str]:
    """Fetch every missing file from release `tag`, verify it, and move it into place.

    A file is written to `<name>.part` and renamed only once its hash matches, so an interrupted or
    tampered download never becomes a file `clapback_embed` would load. Returns the files fetched.
    Raises on a network failure or a hash mismatch; the caller decides whether to retry.
    """
    import httpx

    directory = directory or model_dir()
    directory.mkdir(parents=True, exist_ok=True)
    fetched = []
    owns_client = client is None
    client = client or httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(60.0, read=300.0))
    try:
        for name in missing(directory):
            artifact = ARTIFACTS[name]
            part = directory / f"{name}.part"
            url = RELEASE_ASSET_URL.format(tag=tag, name=name)
            logger.info("Downloading %s (%d MB) from %s", name, artifact.size // 1_000_000, url)
            digest = hashlib.sha256()
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                with part.open("wb") as f:
                    async for chunk in response.aiter_bytes(1 << 20):
                        digest.update(chunk)
                        f.write(chunk)
            if digest.hexdigest() != artifact.sha256:
                part.unlink(missing_ok=True)
                raise ValueError(
                    f"{name} from {url} has sha256 {digest.hexdigest()}, expected {artifact.sha256}"
                )
            part.replace(directory / name)
            fetched.append(name)
    finally:
        if owns_client:
            await client.aclose()
    return fetched


async def ensure_present() -> None:
    """Startup: fetch the encoders if this server has none. Never raises.

    The image already has them, so in Docker this is two `stat` calls. A development checkout
    reports "dev" as its version and has no release to download from, so it only logs how to
    produce the files. Until they arrive, embeddings are off exactly as with
    `DISABLE_CLAP_EMBEDDINGS`, and the next sync after they land picks the backlog up.
    """
    absent = missing()
    if not absent:
        return
    tag = get_app_version()
    if tag == "dev":
        logger.warning(
            "CLAP encoders missing from %s (%s); embeddings are off. A development server has no "
            "release to download them from: copy them from an image, or export them with "
            "clapback's scripts/export_models.py",
            model_dir(),
            ", ".join(absent),
        )
        return
    try:
        fetched = await download(tag)
        logger.info("CLAP encoders ready in %s (fetched %s)", model_dir(), ", ".join(fetched))
    except Exception:
        logger.exception("Could not fetch the CLAP encoders for %s; embeddings stay off", tag)


def main(argv: list[str]) -> int:
    if len(argv) < 1 or argv[0] != "verify":
        print(__doc__.strip().splitlines()[-1].strip())
        return 2
    directory = Path(argv[1]) if len(argv) > 1 else model_dir()
    problems = verify(directory)
    for problem in problems:
        print(problem)
    if not problems:
        print(f"CLAP encoders in {directory} match the pinned hashes.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
