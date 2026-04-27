"""Database models package.

Re-exports all models and enums for backward compatibility.
All existing imports like `from app.db.models import Track` continue to work.
"""

from .artists import ArtistCheckCache, ArtistInfo, ExternalAlbumCache
from .base import (
    AlbumType,
    Base,
    ChangeScope,
    ChangeSource,
    ChangeStatus,
    TrackStatus,
)
from .frontend_log import FrontendLog
from .metadata import ProposedChange
from .playlists import Playlist, PlaylistTrack, SmartPlaylist
from .profiles import (
    LastfmProfile,
    Profile,
    ProfileFavorite,
    ProfilePlayHistory,
)
from .spotify import SpotifyImport
from .tracks import ANALYSIS_FEATURE_COLUMNS, Track, TrackAnalysis, TrackVideo

__all__ = [
    # Base
    "Base",
    # Enums
    "AlbumType",
    "ChangeScope",
    "ChangeSource",
    "ChangeStatus",
    "TrackStatus",
    # Models
    "ArtistCheckCache",
    "ArtistInfo",
    "ExternalAlbumCache",
    "FrontendLog",
    "LastfmProfile",
    "Playlist",
    "PlaylistTrack",
    "Profile",
    "ProfileFavorite",
    "ProfilePlayHistory",
    "ProposedChange",
    "SmartPlaylist",
    "SpotifyImport",
    "Track",
    "TrackAnalysis",
    "TrackVideo",
    "ANALYSIS_FEATURE_COLUMNS",
]
