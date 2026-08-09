"""Inbound authentication — the server token (ADR-0045 point 1).

Familiar had no inbound authentication at all. The whole surface was an `X-Profile-ID` header, and
`GET /api/v1/profiles` hands out every profile ID unauthenticated, so the header was never a secret
and never a claim. ADR-0045 point 3 keeps it as a *selector* — which profile a request acts as —
and puts the question of whether a request may act at all here.

**Why a middleware rather than a router dependency.** `/mcp` is served by `MCPDispatch`, which
answers before the router ever sees the request (`app/mcp/server.py`). A dependency on the API
router would leave the MCP endpoint — the one ADR-0043 exists to expose — as the only unprotected
door. The middleware is ordered inside CORS and outside `MCPDispatch` so that preflight still gets
CORS headers and `/mcp` still gets checked; see the wiring comment in `main.py`.

**Why not bcrypt.** ADR-0045 point 8 asks for bcrypt to be kept or dropped deliberately. Point 7
asked for the shelved Subsonic credentials to be read first, and reading them settles it: that table
stored `password_token` — *the plaintext* — beside the bcrypt hash, because the Subsonic protocol
verifies `md5(password + salt)` and therefore cannot use a one-way hash. The bcrypt hash guarded a
secret that was sitting in the next column. Beyond that, bcrypt is a *password* primitive: it is
deliberately slow so that guessing a human-chosen secret is expensive. This token is 256 bits from
`secrets.token_urlsafe`, where guessing is not the threat. `hmac.compare_digest` against the stored
value is the right tool, and `bcrypt` leaves `pyproject.toml`.

**The token is stored in the clear**, in `data/settings.json`, beside `anthropic_api_key` and the S3
credentials — ADR-0045 point 1 says "beside the outbound credentials" and this is what that means.
It also has to be readable: the operator must copy it into the web app, both Apple clients and any
MCP host, so a write-only hash would make the feature unusable. A hash would protect against an
attacker who can read `settings.json` — who already has every outbound API key in that same file.
"""

from __future__ import annotations

import hmac
import secrets

from starlette.types import ASGIApp, Receive, Scope, Send

TOKEN_HEADER = "X-Familiar-Token"

#: Paths that never require a token, matched against the path with any trailing slash removed.
#:
#: `/api/v1/auth/token` is the bootstrap hole: with no token configured, anything on the tailnet can
#: set one, and whoever sets it first wins. That is exactly today's posture — anything on the tailnet
#: can already delete every profile — so it widens nothing, and it is the only way to configure a
#: server that is not already configured. Once a token *is* set, rotating and revoking it require
#: holding the current one, which is enforced in the route rather than here.
PUBLIC_PATHS = frozenset(
    {
        "/health",
        "/api/v1/health",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/api/v1/auth/token",
    }
)

#: Prefixes the token gate applies to. Everything else — the built SPA, its assets, the embed
#: document — is served to a browser that has no way to set a header, and serving an application
#: shell is not the sensitive act. Its API calls land on `/api/` and are checked there.
PROTECTED_PREFIXES = ("/api/", "/mcp")


def generate_token() -> str:
    """Mint a new server token. 32 bytes, URL-safe, so it survives being pasted into a config."""
    return secrets.token_urlsafe(32)


def token_matches(presented: str | None, configured: str | None) -> bool:
    """Constant-time comparison of a presented token against the configured one.

    Returns False when either side is absent rather than treating "no token configured" as a pass —
    that decision belongs to the caller, which has to distinguish *unconfigured* (allow, ADR-0045
    ships in phases) from *wrong* (refuse).
    """
    if not presented or not configured:
        return False
    return hmac.compare_digest(presented, configured)


def path_requires_token(path: str) -> bool:
    """Whether a request path is behind the token gate."""
    normalised = path.rstrip("/") or "/"
    if normalised in PUBLIC_PATHS:
        return False
    return normalised == "/mcp" or normalised.startswith(PROTECTED_PREFIXES)


def extract_token(scope: Scope) -> str | None:
    """Read the token from the request, accepting a bearer header as well as the custom one.

    An MCP host that can set `Authorization: Bearer <token>` but not an arbitrary header is common
    enough that refusing it would cost more than accepting it. Both name the same single token.
    """
    header_name = TOKEN_HEADER.lower().encode()
    for raw_name, raw_value in scope.get("headers", []):
        if raw_name.lower() == header_name:
            return raw_value.decode("latin-1").strip() or None
    for raw_name, raw_value in scope.get("headers", []):
        if raw_name.lower() == b"authorization":
            value = raw_value.decode("latin-1").strip()
            if value.lower().startswith("bearer "):
                return value[7:].strip() or None
    return None


class TokenAuthMiddleware:
    """Refuse unauthenticated requests to the API and to MCP, when a token is configured.

    **Off when no token is configured**, which is how ADR-0045 lands without breaking every client
    at once. Point 5 — on by default, and refuse to listen on a non-loopback interface with no token
    — is deliberately a later phase, because turning enforcement on before the clients can present a
    token would take the library offline rather than secure it.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        # CORS preflight carries no custom headers by definition — the browser is *asking* which
        # headers it may send. Refusing it here would turn every cross-origin call into an opaque
        # CORS failure rather than an honest 401.
        if scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        if not path_requires_token(scope.get("path", "")):
            await self.app(scope, receive, send)
            return

        from app.services.app_settings import get_app_settings_service

        configured = get_app_settings_service().get().access_token
        if not configured:
            await self.app(scope, receive, send)
            return

        if token_matches(extract_token(scope), configured):
            await self.app(scope, receive, send)
            return

        await self._refuse(scope, send)

    @staticmethod
    async def _refuse(scope: Scope, send: Send) -> None:
        """Emit the project's error envelope by hand.

        A middleware cannot raise `HTTPException` and have `main.py`'s handlers normalise it — those
        run inside the router. Built here so a 401 looks like every other error to a generated
        client, `x-request-id` included when `RequestIDMiddleware` has already set one.
        """
        import json

        request_id = scope.get("state", {}).get("request_id") if scope.get("state") else None
        body = {
            "error": True,
            "status_code": 401,
            "message": "Authentication required",
            "detail": f"Send the server token in the {TOKEN_HEADER} header.",
        }
        if request_id:
            body["request_id"] = request_id
        payload = json.dumps(body).encode()
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(payload)).encode()),
            # Names the scheme so an MCP host or generated client can react to the challenge
            # instead of guessing from the body.
            (b"www-authenticate", b'Bearer realm="Familiar"'),
        ]
        if request_id:
            headers.append((b"x-request-id", request_id.encode()))
        await send({"type": "http.response.start", "status": 401, "headers": headers})
        await send({"type": "http.response.body", "body": payload})
