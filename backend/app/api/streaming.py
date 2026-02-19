"""Shared streaming utilities for serving audio files with range request support."""

import logging
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import Request
from starlette.responses import StreamingResponse

logger = logging.getLogger(__name__)


async def stream_file(file_path: Path, request: Request, mime_type: str) -> StreamingResponse:
    """Stream a file with HTTP range request support.

    Used by both the main tracks API and the Subsonic API.
    """
    file_size = file_path.stat().st_size
    range_header = request.headers.get("range")

    if range_header:
        range_spec = range_header.replace("bytes=", "")
        range_parts = range_spec.split("-")
        start = int(range_parts[0]) if range_parts[0] else 0
        end = int(range_parts[1]) if range_parts[1] else file_size - 1

        start = max(0, min(start, file_size - 1))
        end = max(start, min(end, file_size - 1))
        content_length = end - start + 1

        logger.debug("Range request: %s bytes=%d-%d (%d bytes)", file_path.name, start, end, content_length)

        async def stream_range() -> AsyncIterator[bytes]:
            try:
                with open(file_path, "rb") as f:
                    f.seek(start)
                    remaining = content_length
                    chunk_size = 64 * 1024
                    while remaining > 0:
                        read_size = min(chunk_size, remaining)
                        data = f.read(read_size)
                        if not data:
                            break
                        remaining -= len(data)
                        yield data
            except OSError:
                logger.exception("IO error streaming range for %s", file_path)

        return StreamingResponse(
            stream_range(),
            status_code=206,
            media_type=mime_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(content_length),
                "Cache-Control": "private, max-age=3600",
            },
        )
    else:
        logger.debug("Full file request: %s (%d bytes)", file_path.name, file_size)

        async def stream_full() -> AsyncIterator[bytes]:
            try:
                with open(file_path, "rb") as f:
                    chunk_size = 64 * 1024
                    while chunk := f.read(chunk_size):
                        yield chunk
            except OSError:
                logger.exception("IO error streaming full file %s", file_path)

        return StreamingResponse(
            stream_full(),
            media_type=mime_type,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
                "Cache-Control": "private, max-age=3600",
            },
        )
