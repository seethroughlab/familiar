"""Fix FLAC files that cause Chromium playback errors.

Two classes of issues:
1. Missing PTS timestamps — Chromium's FLAC demuxer requires PTS on audio packets.
   Some encoders don't write these, causing: "FFmpegDemuxer: PTS is not defined".
   Re-muxing with `-c:a copy` is lossless and fixes this.

2. Corrupted/malformed frames — Chromium's decoder rejects packets with bad data,
   causing: "PIPELINE_ERROR_DECODE: Failed to send audio packet for decoding".
   A full re-encode with `-c:a flac` rebuilds all frames and fixes corruption.
"""

import asyncio
import logging
import os
import tempfile
from pathlib import Path

from app.services.metadata import BROWSER_SUPPORTED_CODECS

logger = logging.getLogger(__name__)


async def detect_codec(file_path: Path) -> tuple[str | None, int]:
    """Return (codec_name, bits_per_raw_sample) via ffprobe."""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "quiet",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_name,bits_per_raw_sample",
        "-of", "csv=p=0",
        str(file_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return None, 0

    line = stdout.decode().strip()
    if not line:
        return None, 0

    parts = line.split(",")
    codec = parts[0] if parts[0] and parts[0] != "N/A" else None
    bits = 0
    if len(parts) > 1 and parts[1] and parts[1] != "N/A":
        try:
            bits = int(parts[1])
        except ValueError:
            pass
    return codec, bits


async def needs_transcode_check(file_path: Path) -> bool:
    """Check if file's codec is unsupported by browsers."""
    codec, bits = await detect_codec(file_path)
    if not codec:
        # ffprobe failed — safer to transcode than risk browser decode failure
        return True
    if codec not in BROWSER_SUPPORTED_CODECS:
        return True
    if codec == "flac" and bits > 24:
        return True
    if codec.startswith("pcm_") and bits > 24:
        return True
    return False


async def transcode_to_file(source: Path, dest: Path) -> None:
    """Transcode audio file to FLAC, writing a complete file to dest.

    Unlike piping to stdout, this produces proper streaminfo + seektable headers,
    enabling Content-Length and range requests when served.
    """
    # Write to a temp file first, then rename for atomicity
    fd, tmp_path = tempfile.mkstemp(suffix=".flac", dir=dest.parent)
    os.close(fd)
    tmp = Path(tmp_path)

    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-i", str(source),
            "-c:a", "flac",
            "-f", "flac",
            str(tmp),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError(f"ffmpeg timed out transcoding {source.name}")

        if proc.returncode != 0:
            raise RuntimeError(
                f"ffmpeg transcode failed (rc={proc.returncode}) for {source.name}: "
                f"{stderr.decode()[:500]}"
            )

        if tmp.stat().st_size == 0:
            raise RuntimeError(f"Transcoded file is empty for {source.name}")

        os.replace(tmp, dest)
        logger.info("Transcoded to FLAC cache: %s → %s (%d bytes)", source.name, dest.name, dest.stat().st_size)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


async def needs_remux(file_path: Path) -> bool:
    """Check if a FLAC file is missing PTS timestamps.

    Uses ffprobe to read the first audio packet's PTS.
    Returns True if PTS is missing (N/A), False if present.
    """
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v", "quiet",
        "-select_streams", "a:0",
        "-show_entries", "packet=pts",
        "-read_intervals", "%+#1",
        "-of", "csv=p=0",
        str(file_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        logger.warning("ffprobe timed out checking PTS for %s", file_path.name)
        return False

    pts_value = stdout.decode().strip().rstrip(",")
    if not pts_value or pts_value == "N/A":
        return True

    # Valid numeric PTS means file is fine
    try:
        int(pts_value)
        return False
    except ValueError:
        # Unexpected output — don't remux
        logger.warning("Unexpected ffprobe PTS output for %s: %r", file_path.name, pts_value)
        return False


async def has_decode_errors(file_path: Path) -> bool:
    """Check if an audio file has decode errors by running a full decode pass.

    Uses ffmpeg to decode the entire file to null, capturing any error output.
    Returns True if decode errors are found.
    """
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-v", "error",
        "-i", str(file_path),
        "-f", "null", "-",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        logger.warning("ffmpeg validation timed out for %s", file_path.name)
        return False

    errors = stderr.decode().strip()
    if errors:
        logger.info("Decode errors found in %s: %s", file_path.name, errors[:500])
        return True
    return False
