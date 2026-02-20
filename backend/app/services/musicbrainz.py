"""Backward-compatibility shim. Moved to app.services.metadata.musicbrainz."""

from app.services.metadata.musicbrainz import *  # noqa: F401,F403
from app.services.metadata.musicbrainz import (  # noqa: F401
    _normalize_for_comparison,
    _select_best_release,
    get_recording_by_id,
    search_recording,
    get_artist_by_id,
    get_release_by_id,
    enrich_track,
    search_artist,
    get_artist_releases_recent,
)
