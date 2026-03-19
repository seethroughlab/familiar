"""Library organization service for previewing music file reorganization."""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import MUSIC_LIBRARY_PATH
from app.db.models import Track, TrackStatus

logger = logging.getLogger(__name__)

# Default organization templates
TEMPLATES = {
    "artist-album": "{artist}/{album}/{track_number} - {title}",
    "artist-album-disc": "{artist}/{album}/Disc {disc_number}/{track_number} - {title}",
    "genre-artist-album": "{genre}/{artist}/{album}/{track_number} - {title}",
    "year-artist-album": "{year}/{artist}/{album}/{track_number} - {title}",
    "flat": "{artist} - {album} - {track_number} - {title}",
}

# Characters not allowed in filenames (Windows + macOS + Linux)
INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Characters to replace with alternatives
CHAR_REPLACEMENTS = {
    ":": " -",
    "/": "-",
    "\\": "-",
    "?": "",
    "*": "",
    "<": "",
    ">": "",
    "|": "-",
    '"': "'",
}


def sanitize_filename(name: str | None, default: str = "Unknown") -> str:
    """Sanitize a string for use as a filename component.

    - Replaces invalid characters
    - Strips leading/trailing whitespace and dots
    - Limits length to 200 characters
    - Returns default if empty
    """
    if not name:
        return default

    # Replace known problematic characters with alternatives
    result = name
    for char, replacement in CHAR_REPLACEMENTS.items():
        result = result.replace(char, replacement)

    # Remove any remaining invalid characters
    result = INVALID_CHARS.sub("", result)

    # Strip whitespace and dots (dots at start are hidden files on Unix)
    result = result.strip().strip(".")

    # Limit length
    if len(result) > 200:
        result = result[:200].strip()

    return result or default


@dataclass
class OrganizeResult:
    """Result of organizing a track."""
    track_id: UUID
    old_path: str
    new_path: str | None
    status: Literal["moved", "skipped", "error"]
    message: str


@dataclass
class OrganizeStats:
    """Statistics from an organization operation."""
    total: int
    moved: int
    skipped: int
    errors: int
    results: list[OrganizeResult]


class LibraryOrganizer:
    """Previews music file reorganization according to a template.

    Only considers files with complete metadata to avoid creating
    messy folder structures from poorly-tagged files.
    """

    def __init__(self, db: AsyncSession, library_root: Path | None = None):
        self.db = db
        self.library_root = library_root or MUSIC_LIBRARY_PATH

    def _has_complete_metadata(self, track: Track) -> bool:
        """Check if track has enough metadata for organization."""
        return bool(
            track.title
            and track.artist
            and track.album
        )

    def _format_path(self, track: Track, template: str) -> Path:
        """Format a path from template and track metadata."""
        # Build substitution dict with sanitized values
        subs = {
            "artist": sanitize_filename(track.album_artist or track.artist),
            "album": sanitize_filename(track.album),
            "title": sanitize_filename(track.title),
            "genre": sanitize_filename(track.genre, "Unknown Genre"),
            "year": str(track.year) if track.year else "Unknown Year",
            "track_number": str(track.track_number or 0).zfill(2),
            "disc_number": str(track.disc_number or 1),
        }

        # Get file extension from current path
        ext = Path(track.file_path).suffix

        # Format template and add extension
        formatted = template.format(**subs)
        return self.library_root / f"{formatted}{ext}"

    async def preview_track(
        self,
        track_id: UUID,
        template: str = TEMPLATES["artist-album"],
    ) -> OrganizeResult:
        """Preview what would happen if a track was organized.

        Does not move any files.
        """
        result = await self.db.execute(
            select(Track).where(Track.active_filter(), Track.id == track_id)
        )
        track = result.scalar_one_or_none()

        if not track:
            return OrganizeResult(
                track_id=track_id,
                old_path="",
                new_path=None,
                status="error",
                message="Track not found",
            )

        if not self._has_complete_metadata(track):
            return OrganizeResult(
                track_id=track_id,
                old_path=track.file_path,
                new_path=None,
                status="skipped",
                message="Incomplete metadata (needs title, artist, album)",
            )

        new_path = self._format_path(track, template)

        if Path(track.file_path) == new_path:
            return OrganizeResult(
                track_id=track_id,
                old_path=track.file_path,
                new_path=str(new_path),
                status="skipped",
                message="Already at target path",
            )

        return OrganizeResult(
            track_id=track_id,
            old_path=track.file_path,
            new_path=str(new_path),
            status="moved",  # Would be moved
            message="Ready to move",
        )

    async def preview_all(
        self,
        template: str = TEMPLATES["artist-album"],
        limit: int = 100,
    ) -> OrganizeStats:
        """Preview organization for all tracks (limited).

        Returns what would happen without moving any files.
        """
        query = select(Track).where(Track.active_filter())
        if limit:
            query = query.limit(limit)

        result = await self.db.execute(query)
        tracks = result.scalars().all()

        stats = OrganizeStats(
            total=len(tracks),
            moved=0,
            skipped=0,
            errors=0,
            results=[],
        )

        for track in tracks:
            organize_result = await self.preview_track(track.id, template)
            stats.results.append(organize_result)

            if organize_result.status == "moved":
                stats.moved += 1
            elif organize_result.status == "skipped":
                stats.skipped += 1
            elif organize_result.status == "error":
                stats.errors += 1

        return stats


def get_available_templates() -> dict[str, str]:
    """Get all available organization templates."""
    return TEMPLATES.copy()
