"""Backward-compatibility shim. Moved to app.services.metadata.musicbrainz."""

from app.services.metadata.musicbrainz import *  # noqa: F401,F403
from app.services.metadata.musicbrainz import (  # noqa: F401
    _normalize_for_comparison,
    _select_best_release,
    enrich_track,
    get_artist_by_id,
    get_artist_releases_recent,
    get_recording_by_id,
    get_release_by_id,
    search_artist,
    search_recording,
)
