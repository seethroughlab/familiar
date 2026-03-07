"""Database models package.

Re-exports all models and enums for backward compatibility.
All existing imports like `from app.db.models import Track` continue to work.
"""

from .artists import ArtistInfo
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
    "ArtistInfo",
    "FrontendLog",
    "LastfmProfile",
    "Playlist",
    "PlaylistTrack",
    "Profile",
    "ProfileFavorite",
    "ProfilePlayHistory",
    "ProposedChange",
    "SmartPlaylist",
    "Track",
    "TrackAnalysis",
    "TrackVideo",
    "ANALYSIS_FEATURE_COLUMNS",
]
