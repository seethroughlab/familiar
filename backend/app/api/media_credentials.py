"""The three credentials a media request may carry (ADR-0176 points 1–6).

Media — streams, artwork, artist images, video and avatars, the shapes in `MEDIA_ROUTES` — is read
by consumers that cannot all send a header: a network speaker fetches its URL itself, and the web
admin shows artwork with `<img>`. So a media read is authorized by any one of:

- **the server token** in the header, exactly as on the rest of the API (the Apple clients);
- **a media cookie**, for the web admin's `<img>` (`POST /auth/media-cookie` sets it);
- **a signed URL**, `?exp=<unix>&sig=<hmac>`, minted by the server for a speaker and never by a client.

**Every key here is derived from the server token**, so rotating the token re-keys signatures and
invalidates cookies in the same moment it signs clients out (point 5). Nothing new is stored: with
no token there is nothing to derive from, no URL is signed, and ADR-0171's exposure rules decide.

**Not enforced yet** (`MEDIA_ENFORCED`). Point 8 waits until no App Store build that omits the header
is still offered — 1.6 and 1.7 (build 78) send nothing on media. Until then the gate checks nothing on
media, and this module is exercised by its tests and by the clients that already send credentials.
Phase 4 is flipping `MEDIA_ENFORCED`, then making media `Cache-Control: private`.
"""

from __future__ import annotations

import hmac
import time
from hashlib import sha256
from typing import Literal
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from starlette.types import Scope

from app.api.auth import MEDIA_METHODS, MEDIA_ROUTES, extract_token, token_matches

# Signatures are kept out of logs by `app.logging_config.redact_credentials`, which the access log
# applies to every line (point 6).

#: Phase 4 of ADR-0176. While False, a media request with no credential is still served.
MEDIA_ENFORCED = False

COOKIE_NAME = "familiar_media"
#: The cookie is sent only to the API, and honoured only on media reads (`presented_credential`).
COOKIE_PATH = "/api/v1"
#: A month. The web admin asks for a fresh one every time it starts with a token, so this only
#: bounds how long a closed tab's cookie outlives it; rotation ends it sooner.
COOKIE_MAX_AGE_S = 30 * 24 * 3600

EXP_PARAM = "exp"
SIG_PARAM = "sig"

#: How long past a track's own length a speaker's URL stays valid: a pause, a re-buffer, the
#: device's own range re-fetches. Measured, not guessed (ADR-0176 follow-up): on the NAS on
#: 2026-11-10 the longest track was 11,626 s (3 h 14 min) and 97 tracks ran over an hour, so a fixed
#: lifetime short enough to mean anything would cut the long ones off mid-play.
SIGNED_URL_MARGIN_S = 4 * 3600
#: When the track's length is unknown: the longest measured track plus the margin, rounded up.
SIGNED_URL_DEFAULT_LIFETIME_S = 8 * 3600

Credential = Literal["header", "cookie", "signature"]

_KEY_LABEL = b"familiar-media-credentials-v1"
_SIG_HEX = 32  # 128 bits of HMAC-SHA256


def is_media_request(path: str, method: str) -> bool:
    """A read of one of the media shapes — the only requests these credentials can authorize."""
    normalised = path.rstrip("/") or "/"
    return method.upper() in MEDIA_METHODS and any(r.match(normalised) for r in MEDIA_ROUTES)


def _key(token: str, purpose: bytes) -> bytes:
    """A key for one purpose, derived from the server token so rotating the token re-keys it."""
    return hmac.new(token.encode(), _KEY_LABEL + b"/" + purpose, sha256).digest()


def _api_path(path: str) -> str:
    """The part of a path the server routes on, so a URL built on a proxy prefix still verifies."""
    at = path.find("/api/v1/")
    return path[at:] if at >= 0 else path


def _signature(token: str, path: str, expires_at: int) -> str:
    # "read" is the method class: a signature never authorizes anything but GET/HEAD, and the
    # `Range` a speaker sends varies per request, so it is deliberately not covered (point 2).
    message = f"read\n{_api_path(path)}\n{expires_at}".encode()
    return hmac.new(_key(token, b"url"), message, sha256).hexdigest()[:_SIG_HEX]


def sign_url(url: str, token: str, *, lifetime_s: int, now: float | None = None) -> str:
    """Append `exp` and `sig` to a media URL for a device that can send neither header nor cookie.

    Only the server calls this, for the URL it hands a speaker. Existing query parameters are kept;
    any `exp`/`sig` already present are replaced rather than duplicated.
    """
    expires_at = int((time.time() if now is None else now) + lifetime_s)
    parts = urlsplit(url)
    query = [
        (k, v)
        for k, vs in parse_qs(parts.query, keep_blank_values=True).items()
        if k not in (EXP_PARAM, SIG_PARAM)
        for v in vs
    ]
    query += [(EXP_PARAM, str(expires_at)), (SIG_PARAM, _signature(token, parts.path, expires_at))]
    return urlunsplit(parts._replace(query=urlencode(query)))


def speaker_url_lifetime(duration_s: float | None) -> int:
    """How long a speaker's URL for one track stays valid: the track, plus room to pause."""
    if not duration_s or duration_s <= 0:
        return SIGNED_URL_DEFAULT_LIFETIME_S
    return int(duration_s) + SIGNED_URL_MARGIN_S


def signature_valid(path: str, query_string: str, token: str, now: float | None = None) -> bool:
    params = parse_qs(query_string, keep_blank_values=True)
    exp, sig = params.get(EXP_PARAM, [""])[-1], params.get(SIG_PARAM, [""])[-1]
    if not exp.isdigit() or not sig:
        return False
    if int(exp) < (time.time() if now is None else now):
        return False
    return hmac.compare_digest(sig, _signature(token, path, int(exp)))


def cookie_value(token: str) -> str:
    """The media cookie: derived from the token, so it is no use as the token itself."""
    return hmac.new(_key(token, b"cookie"), b"media-read", sha256).hexdigest()


def _cookie(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name.lower() != b"cookie":
            continue
        for part in value.decode("latin-1").split(";"):
            key, _, val = part.strip().partition("=")
            if key == COOKIE_NAME:
                return val or None
    return None


def presented_credential(scope: Scope, configured: str, now: float | None = None) -> Credential | None:
    """Which valid credential a media request carries, or None.

    Only meaningful for a media read; the caller checks `is_media_request` first, which is what
    keeps the cookie from ever authorizing an action (point 3).
    """
    if token_matches(extract_token(scope), configured):
        return "header"
    cookie = _cookie(scope)
    if cookie and hmac.compare_digest(cookie, cookie_value(configured)):
        return "cookie"
    query = scope.get("query_string", b"").decode("latin-1")
    if query and signature_valid(scope.get("path", ""), query, configured, now):
        return "signature"
    return None
