"""Artwork keys a caller cannot derive (ADR-0176 Phase 1).

Artwork was served without any credential (`MEDIA_ROUTES`, ADR-0045), because an `<img>` and a
casting device cannot send the token; since ADR-0176 Phase 4 it takes a cookie or a signed URL
instead. A tokenless server still serves it to whoever ADR-0171 lets in, so a key must stay one
nobody can guess. Since ADR-0052 an
album's key is its `Album.id`, a UUID. But a track the album resolver could not place still files
its artwork under `compute_album_hash(artist, album)`: sixteen hex digits anyone can compute for a
guessed album. Asking `GET /api/v1/artwork/<that>/thumb` (or `/artwork/status/<that>`) answered
whether this library has the album: an oracle over the collection.

So outside this server a hash key travels as `<hash>.<mac>`, the MAC keyed by a secret the server
mints once and keeps in `settings.json`. Every route that hands a key out issues that form
(`issue`); every route that takes one accepts only it, or a UUID (`accept`). A bare hash gets the same
404 as a missing file. Files on disk keep their names: the MAC is checked, then dropped.

Neither client derives keys: the web app takes them from `/artwork/queue` responses, and the Apple
app does not use these routes. So nothing a client sends changes.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from uuid import UUID

_HASH = re.compile(r"^[0-9a-f]{16}$")
_ISSUED = re.compile(r"^([0-9a-f]{16})\.([0-9a-f]{16})$")


def _secret() -> bytes:
    """This server's artwork secret, minted on first use. Rotating it re-keys every hash URL."""
    from app.services.app_settings import get_app_settings_service

    service = get_app_settings_service()
    secret = service.get().artwork_key_secret
    if not secret:
        secret = secrets.token_hex(32)
        service.update(artwork_key_secret=secret)
    return bytes.fromhex(secret)


def _mac(album_hash: str) -> str:
    return hmac.new(_secret(), album_hash.encode(), hashlib.sha256).hexdigest()[:16]


def _is_uuid(key: str) -> bool:
    try:
        return str(UUID(key)) == key.lower()
    except ValueError:
        return False


def issue(key: str) -> str:
    """The form of an internal artwork key that may leave the server."""
    if _HASH.match(key):
        return f"{key}.{_mac(key)}"
    return key


def accept(key: str) -> str | None:
    """The internal key for one a caller sent, or None if it is not one this server issued.

    A UUID is accepted as it is: it cannot be guessed. A hash only with its MAC. Anything else,
    including a bare derivable hash, is refused.
    """
    if _is_uuid(key):
        return key.lower()
    match = _ISSUED.match(key)
    if match and hmac.compare_digest(match.group(2), _mac(match.group(1))):
        return match.group(1)
    return None
