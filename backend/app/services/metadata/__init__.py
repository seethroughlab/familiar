"""Metadata subpackage.

Re-exports from reader.py for backward compatibility:
    from app.services.metadata import extract_metadata
"""

from app.services.metadata.reader import extract_metadata

__all__ = ["extract_metadata"]
