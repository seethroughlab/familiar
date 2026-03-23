"""Metadata subpackage.

Re-exports from reader.py for backward compatibility:
    from app.services.metadata import extract_metadata
"""

from app.services.metadata.reader import BROWSER_SUPPORTED_CODECS, extract_metadata

__all__ = ["BROWSER_SUPPORTED_CODECS", "extract_metadata"]
