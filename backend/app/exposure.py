"""Who may use a server that has no token (ADR-0171).

One policy, read by every launcher and by the token gate, so that "no token" cannot mean "public"
by accident. Before ADR-0171, `TokenAuthMiddleware` let every request through whenever no token was
configured. `python -m app.serve` decided about tokens at start-up, but a server started any other way
(a bare `uvicorn --host 0.0.0.0`, say) skipped that decision and served anyone.

**A tokenless server is LOCAL unless something chose OPEN.** LOCAL serves only requests that are
plainly from this machine:

- the peer is a loopback address,
- nothing forwarded the request (no `Forwarded`, `X-Forwarded-For` or `X-Real-IP`): a reverse proxy
  on the same host makes a remote browser look like loopback, and
- the `Host` names loopback, so a page using DNS rebinding cannot reach the server through a name it
  controls (ADR-0171 point 7).

OPEN serves anyone, and something has to choose it:

- `FAMILIAR_OPEN_SERVER=1` (the demo, and the documented rollback), or
- the launcher finding an existing library that has never had a token (`Start.EXISTING_OPEN`).
  ADR-0171 point 4: an upgrade must not lock out a working installation. That server warns at
  every start. A library whose token was *removed* is `Start.TOKEN_REMOVED`, and LOCAL.

A server with a token is unaffected: the token decides.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Callable
from enum import Enum

from starlette.types import Scope

LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})

FORWARDING_HEADERS = frozenset({b"forwarded", b"x-forwarded-for", b"x-real-ip"})


class Start(Enum):
    """What a server does about its token at start-up (ADR-0141, ADR-0171 point 2)."""

    LOOPBACK = "listening on loopback only"
    HAS_TOKEN = "has a token"
    OPEN_BY_CHOICE = "open by choice"
    NEW = "new: mint a token"
    EXISTING_OPEN = "existing, open"
    TOKEN_REMOVED = "had a token, removed"


class Exposure(Enum):
    """Who a tokenless server serves."""

    LOCAL = "local"
    OPEN = "open"


def is_loopback(host: str) -> bool:
    """Whether a bind address or peer address is loopback. Names other than `localhost` are not."""
    if host.lower() in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def decide(
    *,
    host: str,
    token: str | None,
    open_server: bool,
    has_tracks: Callable[[], bool],
    had_token: bool = False,
) -> Start:
    """The start-up decision alone, without doing any of it. `has_tracks` is only asked when it
    matters, since it needs the database."""
    if is_loopback(host):
        return Start.LOOPBACK
    if token:
        return Start.HAS_TOKEN
    if open_server:
        return Start.OPEN_BY_CHOICE
    if not has_tracks():
        return Start.NEW
    return Start.TOKEN_REMOVED if had_token else Start.EXISTING_OPEN


def exposure_for(start: Start) -> Exposure:
    """What a start-up decision means for a request that arrives while no token is set."""
    if start in (Start.OPEN_BY_CHOICE, Start.EXISTING_OPEN):
        return Exposure.OPEN
    return Exposure.LOCAL


_recorded: Exposure | None = None


def record(exposure: Exposure | None) -> None:
    """Set by the launcher before it starts uvicorn (the same process), or reset by a test."""
    global _recorded
    _recorded = exposure


def current() -> Exposure:
    """The recorded exposure; without a launcher, OPEN only if `FAMILIAR_OPEN_SERVER` says so."""
    if _recorded is not None:
        return _recorded
    from app.config import settings

    return Exposure.OPEN if settings.open_server else Exposure.LOCAL


def _host_name(value: str) -> str:
    """`Host` without its port: `localhost:4400` → `localhost`, `[::1]:4400` → `::1`."""
    value = value.strip().lower()
    if value.startswith("["):
        return value[1:].split("]", 1)[0]
    if value.count(":") == 1:
        return value.split(":", 1)[0]
    return value


def request_is_local(scope: Scope) -> bool:
    """Whether a request plainly comes from this machine, under the module's three rules."""
    client = scope.get("client")
    if not client or not is_loopback(str(client[0])):
        return False
    host = ""
    for raw_name, raw_value in scope.get("headers", []):
        name = raw_name.lower()
        if name in FORWARDING_HEADERS:
            return False
        if name == b"host":
            host = raw_value.decode("latin-1")
    return is_loopback(_host_name(host)) if host else True


def tokenless_allows(scope: Scope) -> bool:
    """Whether a request may proceed while no token is configured."""
    return current() is Exposure.OPEN or request_is_local(scope)
