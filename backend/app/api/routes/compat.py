"""Compatibility routes for paths that have moved (ADR-0079).

**Every alias in this API is in this file.** That is ADR-0079 point 5, and the reason for it is
that an alias scattered beside its handler is an alias nobody deletes. The set is countable by
reading one module, and removing it is one file's worth of work.

How they work, and what each property is for:

- **Invisible.** Every route here is `include_in_schema=False`, so none of them appears in
  `openapi.json`, `/docs`, `/redoc`, the generated Swift client, or anything `lint_openapi.py`
  counts. A newcomer reading the API cannot see them, which is what makes compatibility compatible
  with the goal rather than a compromise of it (point 1).

- **Delegation, never a copy.** Each alias registers the *same function object* the new path
  registers. Not a wrapper that calls it — the same object, so FastAPI resolves identical
  dependencies, validation and response models. Two implementations of one endpoint would drift,
  and the second one would be the untested one (point 2).

- **Announced to machines, not to people.** `Deprecation: true` and a `Sunset` date (RFC 8594) go
  on every response, via a router-level dependency rather than per route. Anything still calling an
  old path can be found in logs, so the removal decision is made on evidence (point 3).

**The removal trigger, written down as point 4 requires.** These five come out when no App Store
build calling `/queue/*` is still offered. At the time of writing the shipping line is `1.2`; check
App Store Connect for `com.familiar.player` before deleting, and note that a self-hosted server may
be older than any app. This is a condition to check, not a date to wait for.

Adding an alias here is not free — see ADR-0079's Tradeoff. Each one is a path the server answers on
that is absent from its own contract.
"""

import re
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.routes.listening import offline, session
from app.api.routes.listening import radio as radio_routes

# RFC 8594 wants an HTTP-date. Fixed rather than computed: a `Sunset` that moves every time the
# server restarts tells a client nothing.
#
# **It is indicative, not the trigger.** ADR-0079 point 4 removes an alias when the last app build
# using the old path is no longer offered — a condition someone checks, not a date that arrives. The
# header exists because RFC 8594 requires one for `Deprecation` to be actionable by a machine; if
# the date passes and the build is still shipping, move the date, not the alias.
SUNSET = "Tue, 31 Aug 2027 23:59:59 GMT"


router = APIRouter(include_in_schema=False)

# ADR-0074 moved these. **Five paths, six routes** — `/queue/session` answers GET and PUT, and the
# ADR's "five aliases" counts paths. Left column is what shipped clients call; the handler is the
# one the new path uses, passed by reference so there is exactly one implementation.
_ALIASES: list[tuple[str, list[str], Callable[..., Any]]] = [
    ("/queue/session", ["GET"], session.get_playback_session),
    ("/queue/session", ["PUT"], session.put_playback_session),
    ("/queue/session/archive", ["GET"], session.list_archived_sessions),
    ("/queue/session/archive/{archive_id}/restore", ["POST"], session.restore_archived_session),
    ("/queue/suggestions", ["POST"], radio_routes.suggestions),
    ("/queue/offline-manifest", ["POST"], offline.offline_manifest),
]

for _path, _methods, _endpoint in _ALIASES:
    router.add_api_route(_path, _endpoint, methods=_methods)


# The alias paths as they arrive on the wire, including the `/api/v1` mount prefix.
_ALIAS_PATTERNS = [
    re.compile("^/api/v1" + re.sub(r"\{[^}]+\}", "[^/]+", path) + "/?$") for path, _, _ in _ALIASES
]


class DeprecatedPathHeaders:
    """Attach `Deprecation` and `Sunset` to every response from a moved path (ADR-0079 point 3).

    **This is middleware rather than a dependency, and the reason is the failure it fixes.** A
    dependency taking `Response` sets headers on an object the *success* path returns; when a
    handler raises — a 401 from `RequiredProfile`, a 503 from a disabled flag — the exception
    handler builds a fresh response and those headers are silently dropped.

    That would have been close to useless in practice. Point 3 exists so the alias can be found in
    logs, and a shipped app calling a moved path *without a valid profile* is precisely a call worth
    finding. Announcing only on success would have hidden the noisiest callers.

    Operating at ASGI level means the headers are attached to whatever response is actually sent,
    by any route, handler or exception handler.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not any(p.match(scope["path"]) for p in _ALIAS_PATTERNS):
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Deprecation"] = "true"
                headers["Sunset"] = SUNSET
            await send(message)

        await self.app(scope, receive, send_with_headers)
