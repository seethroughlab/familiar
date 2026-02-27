import enum
from typing import Any

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all models."""

    type_annotation_map = {
        dict[str, Any]: JSONB,
    }


class AlbumType(enum.Enum):
    """Album classification for proper handling of compilations/soundtracks."""

    ALBUM = "album"
    EP = "ep"
    SINGLE = "single"
    COMPILATION = "compilation"
    SOUNDTRACK = "soundtrack"
    LIVE = "live"


class TrackStatus(enum.Enum):
    """Track file availability status for safe library management.

    Prevents catastrophic deletion when library path is misconfigured.
    Missing tracks are preserved until user explicitly confirms deletion.
    """

    ACTIVE = "active"  # File exists at path
    MISSING = "missing"  # File not found, awaiting user action
    PENDING_DELETION = "pending_deletion"  # Missing >30 days, suggested for cleanup


class ChangeStatus(enum.Enum):
    """Status of a proposed metadata change."""

    PENDING = "pending"  # Awaiting user review
    REJECTED = "rejected"  # User rejected
    APPLIED = "applied"  # Successfully applied


class ChangeSource(enum.Enum):
    """Source that generated a proposed change."""

    USER_REQUEST = "user_request"  # User explicitly asked LLM to fix
    LLM_SUGGESTION = "llm_suggestion"  # LLM noticed while doing something else
    MUSICBRAINZ = "musicbrainz"  # From MusicBrainz lookup
    SPOTIFY = "spotify"  # From Spotify lookup
    AUTO_ENRICHMENT = "auto_enrichment"  # From auto-enrichment service


class ChangeScope(enum.Enum):
    """Scope of changes to apply."""

    DB_ONLY = "db_only"  # Just update Familiar's database
    DB_AND_ID3 = "db_and_id3"  # Also write to audio file tags
    DB_ID3_FILES = "db_id3_files"  # Also rename/move files


class ExternalTrackSource(enum.Enum):
    """Source of an external/missing track."""

    SPOTIFY_PLAYLIST = "spotify_playlist"
    SPOTIFY_FAVORITE = "spotify_favorite"
    PLAYLIST_IMPORT = "playlist_import"
    LLM_RECOMMENDATION = "llm_recommendation"
    MANUAL = "manual"
    NEW_RELEASE = "new_release"
