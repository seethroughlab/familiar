"""Quick import endpoints (scan-path)."""

import logging
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.exceptions import (
    InvalidPathError,
    NotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class ScanPathEntry(BaseModel):
    """A directory entry from scan-path."""
    name: str
    file_count: int
    total_size_bytes: int


@router.get("/import/scan-path", response_model=list[ScanPathEntry])
async def scan_path(path: str) -> list[ScanPathEntry]:
    """List subdirectories at a local path with audio file counts.

    Useful for discovering what's available for import at a given path
    (e.g. a mounted volume of downloaded music).

    Args:
        path: Absolute path inside the container to scan.
    """
    from app.config import AUDIO_EXTENSIONS

    scan_dir = Path(path)
    if not scan_dir.exists():
        raise NotFoundError(f"Path does not exist: {path}")
    if not scan_dir.is_dir():
        raise InvalidPathError(f"Path is not a directory: {path}")

    entries = []
    for child in sorted(scan_dir.iterdir()):
        if not child.is_dir():
            continue
        audio_files = [
            f for f in child.rglob("*")
            if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
        ]
        if audio_files:
            entries.append(ScanPathEntry(
                name=child.name,
                file_count=len(audio_files),
                total_size_bytes=sum(f.stat().st_size for f in audio_files),
            ))

    return entries
