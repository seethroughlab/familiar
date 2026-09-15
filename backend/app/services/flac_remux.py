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
from dataclasses import dataclass
from pathlib import Path

from app.services.metadata import BROWSER_SUPPORTED_CODECS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TranscodeTarget:
    """What ``transcode_to_file`` produces: a codec, a container, and the name to cache it under.

    Two exist. ``FLAC`` is the original purpose of this module — a lossless remux so a browser can
    play AIFF and odd codecs. ``AAC`` is ADR-0118: a lossy encode so a *phone* can download a
    lossless track at a quarter of the size. Same machinery, same cache, different arguments.
    """

    name: str
    #: Appended to the track id in ``data/transcode_cache``. Both the codec and the container are
    #: in the AAC name so a later change of either — ``libfdk_aac``, say — lands under a new name
    #: and re-encodes rather than serving the old file as if it were the new one.
    cache_suffix: str
    mime_type: str
    #: Everything between ``-i <source>`` and the output path.
    ffmpeg_args: tuple[str, ...]


FLAC = TranscodeTarget(
    name="FLAC",
    cache_suffix=".flac",
    mime_type="audio/flac",
    ffmpeg_args=("-c:a", "flac", "-f", "flac"),
)

#: 256 kbps AAC in an MP4 container (ADR-0118 point 3).
#:
#: ``-vn`` because a Bandcamp FLAC carries its cover as a video stream, and without it ffmpeg
#: tries to put a JPEG in the MP4. ``+faststart`` moves the ``moov`` atom to the front so the file
#: opens without a read to the end, which is what makes a Range request on it seekable. The
#: built-in ``aac`` encoder rather than ``libfdk_aac`` because the image has the one and not the
#: other; at 256 kbps the difference is not the point.
AAC = TranscodeTarget(
    name="AAC",
    cache_suffix=".aac.m4a",
    mime_type="audio/mp4",
    ffmpeg_args=("-vn", "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", "-f", "mp4"),
)


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


async def transcode_to_file(source: Path, dest: Path, target: TranscodeTarget = FLAC) -> None:
    """Transcode audio file to ``target``, writing a complete file to dest.

    Unlike piping to stdout, this produces proper headers (FLAC's streaminfo + seektable; MP4's
    ``moov``), enabling Content-Length and range requests when served.
    """
    # Write to a temp file first, then rename for atomicity. The temp name carries the target's
    # suffix because ffmpeg's muxer for MP4 wants to know what it is writing.
    fd, tmp_path = tempfile.mkstemp(suffix=target.cache_suffix, dir=dest.parent)
    os.close(fd)
    tmp = Path(tmp_path)

    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-i", str(source),
            *target.ffmpeg_args,
            str(tmp),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            # 300 s holds for AAC with margin: measured on the NAS at ~22× realtime on one core
            # (12.4 s for 4:32), a twenty-minute 24/96 track is about a minute.
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
        logger.info(
            "Transcoded to %s cache: %s → %s (%d bytes)",
            target.name, source.name, dest.name, dest.stat().st_size,
        )
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
