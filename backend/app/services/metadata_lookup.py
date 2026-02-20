"""Backward-compatibility shim. Moved to app.services.metadata.lookup."""

from app.services.metadata.lookup import *  # noqa: F401,F403
from app.services.metadata.lookup import (  # noqa: F401
    AlbumCandidate,
    MetadataCandidate,
    MetadataLookupService,
    get_metadata_lookup_service,
)
