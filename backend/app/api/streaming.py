"""Shared streaming utilities for serving audio files with range request support."""

import logging
from pathlib import Path

from fastapi import Request
from starlette.responses import FileResponse

logger = logging.getLogger(__name__)


async def stream_file(file_path: Path, request: Request, mime_type: str) -> FileResponse:
    """Serve a file with HTTP range support.

    Delegates to Starlette's ``FileResponse``, which reads the ``Range`` header off the
    ASGI scope itself and handles 206, 416, multipart ranges, ``ETag`` and
    ``Last-Modified``.

    This replaced a hand-rolled implementation that caused issue #13 — playback dying
    with ``PIPELINE_ERROR_READ: FFmpegDemuxer: data source error`` a couple of times per
    seven minutes of listening. Five defects, in rough order of how much they hurt:

    1. **Blocking I/O on the event loop.** ``open``/``seek``/``read`` ran inline in an
       async generator, 64 KiB at a time. Uvicorn runs ``--workers 1`` (CLAP needs
       ~1.5 GB, so more workers would OOM) and library sync plus background analysis
       share that process, so a sync would stall the loop — p95 latency was measured at
       990 ms and 1036 ms during sync, against ~50 ms idle. A starved media element
       reports a read failure. ``FileResponse`` uses ``anyio`` for both ``stat`` and the
       reads, so file I/O no longer blocks the loop.
    2. **Silent truncation.** ``except OSError`` logged and returned *without*
       re-raising, and a short read hit ``break`` — but the response had already sent
       ``Content-Length: N``. The body then ended early while the header still claimed
       N bytes, which a demuxer cannot tell apart from corruption.
    3. **No ``ETag``/``Last-Modified``**, while still sending
       ``Cache-Control: private, max-age=3600``. With no validator the browser cannot
       revalidate or resume — only refetch blind.
    4. **Suffix ranges served the wrong bytes.** ``bytes=-100`` means the *last* 100
       bytes; splitting on ``-`` gave an empty first field, so it returned bytes 0-100
       with a ``Content-Range`` contradicting the request, under a 206. Demuxers use
       suffix ranges to read trailers.
    5. **No 416, and multipart ranges 500'd.** An unsatisfiable range was clamped into
       the file and served as a bogus single-byte 206; ``bytes=0-10,20-30`` raised
       ``ValueError`` from ``int("100,200")``.

    ``request`` is retained for call-site compatibility and is no longer read here —
    ``FileResponse`` takes the range from the scope.
    """
    return FileResponse(
        path=file_path,
        media_type=mime_type,
        # Preserved from the previous implementation, and only now actually useful:
        # FileResponse supplies the validators that make revalidation possible.
        headers={"Cache-Control": "private, max-age=3600"},
    )
