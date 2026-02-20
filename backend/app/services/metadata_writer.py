"""Backward-compatibility shim. Moved to app.services.metadata.writer."""

from app.services.metadata.writer import *  # noqa: F401,F403
from app.services.metadata.writer import (  # noqa: F401
    WriteResult,
    remove_artwork,
    write_artwork,
    write_lyrics,
    write_metadata,
)
