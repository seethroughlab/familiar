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

logger = logging.getLogger(__name__)


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

    pts_value = stdout.decode().strip()
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


async def remux_flac_in_place(file_path: Path) -> None:
    """Re-mux FLAC through ffmpeg to fix missing PTS. Lossless. Atomic."""
    fd, tmp_path = tempfile.mkstemp(suffix=".flac", dir=file_path.parent)
    os.close(fd)
    tmp = Path(tmp_path)

    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-i", str(file_path),
            "-c:a", "copy",
            "-f", "flac",
            str(tmp),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError(f"ffmpeg timed out re-muxing {file_path.name}")

        if proc.returncode != 0:
            raise RuntimeError(
                f"ffmpeg failed (rc={proc.returncode}) for {file_path.name}: "
                f"{stderr.decode()[:500]}"
            )

        # Sanity check: output should be non-empty and at least 50% of original
        orig_size = file_path.stat().st_size
        tmp_size = tmp.stat().st_size
        if tmp_size == 0 or tmp_size < orig_size * 0.5:
            raise RuntimeError(
                f"Re-muxed file suspicious size: {tmp_size} vs original {orig_size}"
            )

        # Atomic replace (same filesystem)
        os.replace(tmp, file_path)
        logger.info("Re-muxed FLAC for PTS fix: %s (%d → %d bytes)", file_path.name, orig_size, tmp_size)
    except BaseException:
        # Clean up temp file, leave original untouched
        tmp.unlink(missing_ok=True)
        raise


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


REMUX_FORMATS = {
    ".mp3": "mp3",
    ".ogg": "ogg",
    ".m4a": "mp4",
    ".aac": "adts",
    ".wav": "wav",
}


async def remux_audio_in_place(file_path: Path) -> None:
    """Re-mux non-FLAC audio through ffmpeg (-c:a copy). No re-encoding. Atomic."""
    suffix = file_path.suffix.lower()
    fmt = REMUX_FORMATS.get(suffix)
    if not fmt:
        raise ValueError(f"Unsupported format for remux: {suffix}")

    fd, tmp_path = tempfile.mkstemp(suffix=suffix, dir=file_path.parent)
    os.close(fd)
    tmp = Path(tmp_path)

    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-i", str(file_path),
            "-c:a", "copy",
            "-f", fmt,
            str(tmp),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError(f"ffmpeg timed out re-muxing {file_path.name}")

        if proc.returncode != 0:
            raise RuntimeError(
                f"ffmpeg failed (rc={proc.returncode}) for {file_path.name}: "
                f"{stderr.decode()[:500]}"
            )

        # Sanity check: output should be non-empty and at least 50% of original
        orig_size = file_path.stat().st_size
        tmp_size = tmp.stat().st_size
        if tmp_size == 0 or tmp_size < orig_size * 0.5:
            raise RuntimeError(
                f"Re-muxed file suspicious size: {tmp_size} vs original {orig_size}"
            )

        # Atomic replace (same filesystem)
        os.replace(tmp, file_path)
        logger.info(
            "Re-muxed %s for container fix: %s (%d → %d bytes)",
            suffix, file_path.name, orig_size, tmp_size,
        )
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


async def reencode_flac_in_place(file_path: Path) -> None:
    """Re-encode FLAC through ffmpeg to fix corrupted frames. Lossless. Atomic."""
    fd, tmp_path = tempfile.mkstemp(suffix=".flac", dir=file_path.parent)
    os.close(fd)
    tmp = Path(tmp_path)

    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-i", str(file_path),
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
            raise RuntimeError(f"ffmpeg timed out re-encoding {file_path.name}")

        if proc.returncode != 0:
            raise RuntimeError(
                f"ffmpeg re-encode failed (rc={proc.returncode}) for {file_path.name}: "
                f"{stderr.decode()[:500]}"
            )

        # Sanity check: output should be non-empty and at least 50% of original
        orig_size = file_path.stat().st_size
        tmp_size = tmp.stat().st_size
        if tmp_size == 0 or tmp_size < orig_size * 0.5:
            raise RuntimeError(
                f"Re-encoded file suspicious size: {tmp_size} vs original {orig_size}"
            )

        # Atomic replace (same filesystem)
        os.replace(tmp, file_path)
        logger.info(
            "Re-encoded FLAC to fix decode errors: %s (%d → %d bytes)",
            file_path.name, orig_size, tmp_size,
        )
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
