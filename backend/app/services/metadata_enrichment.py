"""Backward-compatibility shim. Moved to app.services.metadata.enrichment."""

from app.services.metadata.enrichment import *  # noqa: F401,F403
from app.services.metadata.enrichment import (  # noqa: F401
    CAA_BASE_URL,
    ENRICHABLE_FIELDS,
    PLACEHOLDER_PATTERNS,
    fetch_cover_art,
    get_missing_fields,
    is_field_missing,
    needs_enrichment,
    write_metadata_to_file,
)
