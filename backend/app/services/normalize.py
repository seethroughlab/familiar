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

    # Normalize quotes to their ASCII forms.
    #
    # **The curly quotes were missing from both classes.** Each held its ASCII form
    # twice — someone typed the curly pair in the comment and plain ones in the pattern
    # — so a typographic apostrophe passed straight through. This feeds
    # compute_album_hash, so it filed one album under two artwork keys; 16 albums and 30
    # tracks on the live library carry a curly apostrophe.
    #
    # The defect survived because ' and the curly form are near-identical in a monospace
    # font. `test_normalize_quotes.py` asserts each character explicitly.
    s = re.sub(r"[‘’´`′']", "'", s)
    s = re.sub(r'[“”«»"]', '"', s)

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
    r'bonus\s*track|edition|version|mono|stereo)[^\)\]]*[\)\]]',
    re.IGNORECASE,
)

_DASH_SUFFIX_RE = re.compile(
    r'\s+-\s+(?:\d{4}\s+)?(?:remaster(?:ed)?|deluxe|expanded|special|anniversary|'
    r'collector|bonus\s*track|edition|version|mono|stereo)\b.*$',
    re.IGNORECASE,
)

_LEADING_ARTICLE_RE = re.compile(r'^(?:the|a|an)\s+', re.IGNORECASE)


_FEAT_RE = re.compile(
    r"""
    \s*                           # optional leading whitespace
    (?:                           # either parenthesized/bracketed…
        [\(\[]                    #   open paren or bracket
        \s*(?:feat\.?|ft\.?|featuring)\s+
        (.+?)                     #   guest artist(s)
        \s*[\)\]]                 #   close paren or bracket
    |                             # …or bare suffix
        \s+(?:feat\.?|ft\.?|featuring)\s+
        (.+)                      #   guest artist(s) to end of string
    )
    \s*$                          # end of string
    """,
    re.IGNORECASE | re.VERBOSE,
)


def extract_primary_artist(artist: str | None) -> tuple[str, str | None]:
    """Extract primary artist and featuring guests from an artist string.

    Splits strings like "Massive Attack Feat. Damon Albarn" into
    ("Massive Attack", "Damon Albarn").

    Handles: feat., ft., featuring, Feat — with/without parens/brackets,
    case-insensitive.

    Returns:
        (primary_artist, featuring_artists_or_None)

    Examples:
        >>> extract_primary_artist("Massive Attack feat. Damon Albarn")
        ('Massive Attack', 'Damon Albarn')
        >>> extract_primary_artist("Radiohead")
        ('Radiohead', None)
        >>> extract_primary_artist("Artist (ft. Guest A & Guest B)")
        ('Artist', 'Guest A & Guest B')
    """
    if not artist or not artist.strip():
        return (artist or "", None)

    m = _FEAT_RE.search(artist)
    if not m:
        return (artist, None)

    primary = artist[: m.start()].strip()
    featuring = (m.group(1) or m.group(2) or "").strip()

    # Safety: don't return an empty primary artist
    if not primary:
        return (artist, None)

    return (primary, featuring or None)


def normalize_for_duplicate_matching(
    name: str | None, *, strip_articles: bool = False
) -> str:
    """Normalize a string for duplicate detection during import.

    Builds on normalize_for_matching() with additional steps:
    - Strip parenthetical suffixes containing release-variant keywords
      (remaster/deluxe/edition/etc.) but preserve identity-bearing suffixes
      (remix, feat, edit, live at).
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

    # Strip dash-prefixed suffixes (Spotify style: "Song - 2011 Remaster")
    s = _DASH_SUFFIX_RE.sub("", s)

    # Strip leading articles for artist matching
    if strip_articles:
        s = _LEADING_ARTICLE_RE.sub("", s)

    # Re-collapse whitespace and strip
    s = " ".join(s.split()).strip()

    return s
