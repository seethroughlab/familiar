"""Backward-compatibility shim. Moved to app.services.metadata.writer."""

from app.services.metadata.writer import *  # noqa: F401,F403
from app.services.metadata.writer import WriteResult, write_artwork, write_lyrics, write_metadata, remove_artwork  # noqa: F401
