"""String normalization utilities for consistent matching.

Used for album/artist name matching to handle variations like:
- Case: "THE" vs "the"
- Diacritics: "Björk" vs "Bjork"
- Quote styles: "Don't" vs "Don't"
- Dashes: "Rock — Roll" vs "Rock - Roll"
- Whitespace: "The  Beatles" vs "The Beatles"
"""

import re
import unicodedata


def normalize_for_matching(name: str | None) -> str:
    """Normalize a string for consistent matching.

    Handles: case, whitespace, quotes, dashes, diacritics.
    Preserves: articles, punctuation structure.

    Args:
        name: The string to normalize

    Returns:
        Normalized string suitable for comparison/hashing

    Examples:
        >>> normalize_for_matching("Björk")
        'bjork'
        >>> normalize_for_matching("Alice In Ultraland")
        'alice in ultraland'
        >>> normalize_for_matching("Don't Stop")
        "don't stop"
    """
    if not name:
        return ""

    s = name.strip()

    # Unicode NFC normalization (compose characters consistently)
    s = unicodedata.normalize("NFC", s)

    # Normalize quotes: ' ' ´ ` ′ → '
    s = re.sub(r"[''´`′]", "'", s)
    s = re.sub(r'[""«»]', '"', s)

    # Normalize dashes: – — − ‐ ‒ ⁻ → -
    s = re.sub(r"[–—−‐‒⁻]", "-", s)

    # Remove diacritics: Björk → Bjork
    # NFKD decomposes characters (é → e + combining accent)
    s = unicodedata.normalize("NFKD", s)
    # Remove combining marks (accents, umlauts, etc.)
    s = "".join(c for c in s if not unicodedata.combining(c))

    # Case fold (better than .lower() for unicode, handles ß → ss)
    s = s.casefold()

    # Collapse whitespace
    s = " ".join(s.split())

    return s


# Regex for parenthetical suffixes commonly found in reissues, remasters, etc.
_PAREN_SUFFIX_RE = re.compile(
    r'\s*[\(\[][^\)\]]*(?:remaster|deluxe|expanded|special|anniversary|collector|'
    r'bonus\s*track|edition|version|feat\.?|ft\.?|featuring|remix|edit|mono|stereo|'
    r'live\s+at)[^\)\]]*[\)\]]',
    re.IGNORECASE,
)

_LEADING_ARTICLE_RE = re.compile(r'^(?:the|a|an)\s+', re.IGNORECASE)


def normalize_for_duplicate_matching(
    name: str | None, *, strip_articles: bool = False
) -> str:
    """Normalize a string for duplicate detection during import.

    Builds on normalize_for_matching() with additional steps:
    - Strip parenthetical suffixes containing remaster/deluxe/feat/remix/etc.
    - Optionally strip leading articles (the/a/an) for artist matching.

    Args:
        name: The string to normalize
        strip_articles: If True, strip leading "the ", "a ", "an " (for artist matching)

    Returns:
        Normalized string suitable for duplicate comparison

    Examples:
        >>> normalize_for_duplicate_matching("Hey Jude (Remastered 2009)")
        'hey jude'
        >>> normalize_for_duplicate_matching("The Beatles", strip_articles=True)
        'beatles'
    """
    s = normalize_for_matching(name)
    if not s:
        return s

    # Strip parenthetical suffixes (remaster, deluxe, feat, remix, etc.)
    s = _PAREN_SUFFIX_RE.sub("", s)

    # Strip leading articles for artist matching
    if strip_articles:
        s = _LEADING_ARTICLE_RE.sub("", s)

    # Re-collapse whitespace and strip
    s = " ".join(s.split()).strip()

    return s
