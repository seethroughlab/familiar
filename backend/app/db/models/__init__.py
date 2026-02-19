"""Database models package.

Re-exports all models and enums for backward compatibility.
All existing imports like `from app.db.models import Track` continue to work.
"""

from .artists import ArtistCheckCache, ArtistInfo, ArtistNewRelease
from .base import (
    AlbumType,
    Base,
    ChangeScope,
    ChangeSource,
    ChangeStatus,
    ExternalTrackSource,
    TrackStatus,
)
from .frontend_log import FrontendLog
from .metadata import ProposedChange
from .playlists import Playlist, PlaylistTrack, SmartPlaylist
from .plugins import Plugin, PluginType
from .profiles import (
    LastfmProfile,
    Profile,
    ProfileExternalFavorite,
    ProfileFavorite,
    ProfilePlayHistory,
    SpotifyFavorite,
    SpotifyProfile,
    SubsonicCredential,
)
from .tracks import ANALYSIS_FEATURE_COLUMNS, ExternalTrack, Track, TrackAnalysis, TrackVideo

__all__ = [
    # Base
    "Base",
    # Enums
    "AlbumType",
    "ChangeScope",
    "ChangeSource",
    "ChangeStatus",
    "ExternalTrackSource",
    "PluginType",
    "TrackStatus",
    # Models
    "ArtistCheckCache",
    "ArtistInfo",
    "ArtistNewRelease",
    "FrontendLog",
    "ExternalTrack",
    "LastfmProfile",
    "Playlist",
    "PlaylistTrack",
    "Plugin",
    "Profile",
    "ProfileExternalFavorite",
    "ProfileFavorite",
    "ProfilePlayHistory",
    "ProposedChange",
    "SmartPlaylist",
    "SpotifyFavorite",
    "SpotifyProfile",
    "SubsonicCredential",
    "Track",
    "TrackAnalysis",
    "TrackVideo",
    "ANALYSIS_FEATURE_COLUMNS",
]
