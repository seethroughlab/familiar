"""Handler mixins for ToolExecutor.

Each mixin provides a group of related tool handler methods
that are composed into the ToolExecutor class via multiple inheritance.
"""

from .analysis import AnalysisHandlersMixin
from .discovery import DiscoveryHandlersMixin
from .library_info import LibraryInfoHandlersMixin
from .metadata import MetadataHandlersMixin
from .playback import PlaybackHandlersMixin
from .playlists import PlaylistHandlersMixin
from .search import SearchHandlersMixin
from .spotify import SpotifyHandlersMixin

__all__ = [
    "AnalysisHandlersMixin",
    "DiscoveryHandlersMixin",
    "LibraryInfoHandlersMixin",
    "MetadataHandlersMixin",
    "PlaybackHandlersMixin",
    "PlaylistHandlersMixin",
    "SearchHandlersMixin",
    "SpotifyHandlersMixin",
]
