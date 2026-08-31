"""Discovery: the background half of finding music you do not own (ADR-0099).

The request path reads `external_album_cache` and never calls out; everything that
talks to MusicBrainz, Last.fm or Bandcamp for discovery lives behind here.
"""

from app.services.discovery.sources import (
    SourceHealthRecorder,
    backoff_seconds,
    get_recorder,
)

__all__ = ["SourceHealthRecorder", "backoff_seconds", "get_recorder"]
