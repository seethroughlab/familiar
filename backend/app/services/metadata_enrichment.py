"""Backward-compatibility shim. Moved to app.services.metadata.enrichment."""

from app.services.metadata.enrichment import *  # noqa: F401,F403
from app.services.metadata.enrichment import (  # noqa: F401
    is_field_missing,
    needs_enrichment,
    get_missing_fields,
    fetch_cover_art,
    write_metadata_to_file,
    ENRICHABLE_FIELDS,
    PLACEHOLDER_PATTERNS,
    CAA_BASE_URL,
)
