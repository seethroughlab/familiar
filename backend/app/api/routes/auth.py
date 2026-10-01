"""Server token management (ADR-0045 point 1).

Issue, read, rotate and revoke the single inbound token. ADR-0045's acceptance notes list rotation
and revocation as a requirement rather than a nicety — *"a token that can only be changed by editing
JSON on the NAS is a token nobody rotates"* — so they exist here from the first commit rather than
being left to a follow-up.

**These operations are deliberately outside the token gate** (`PUBLIC_PATHS` in `app/api/auth.py`)
and re-check the token themselves. The gate cannot protect the endpoint that configures the gate:
on a server with no token, refusing an unauthenticated caller would leave no way to set one. What
that means concretely is that on an unconfigured server, anything that can reach the port can claim
it — which is precisely today's posture, where anything that can reach the port can already delete
every profile. Once a token exists, changing or clearing it requires presenting it.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.api.auth import TOKEN_HEADER, extract_token, generate_token, token_matches
from app.services.app_settings import get_app_settings_service

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenStatus(BaseModel):
    """Whether inbound authentication is configured, and the token if it is."""

    configured: bool
    token: str | None = None
    header: str = TOKEN_HEADER
    #: Running without a token on purpose (`FAMILIAR_OPEN_SERVER`, ADR-0141 point 4). The web admin
    #: warns about an open server only when this is False.
    open_by_choice: bool = False


class TokenIssued(BaseModel):
    """A newly minted token."""

    configured: bool
    token: str
    header: str = TOKEN_HEADER


def _authorised(request: Request) -> bool:
    """True when the caller may change the token: either none is set, or they hold the current one.

    Reads through the same `extract_token` the middleware uses, so a caller that authenticates one
    way (bearer) cannot be rejected here for not using the other.
    """
    configured = get_app_settings_service().get().access_token
    if not configured:
        return True
    return token_matches(extract_token(request.scope), configured)


@router.get("/token", response_model=TokenStatus)
async def get_token(request: Request) -> TokenStatus:
    """Read the current token.

    Returns the value rather than a mask, because the point of it is to be copied into clients and
    it is already readable in `data/settings.json` by anyone who can call this. Reading it requires
    holding it, once one exists.
    """
    from app.api.exceptions import AuthenticationError
    from app.config import settings as env_settings

    settings = get_app_settings_service().get()
    if not settings.access_token:
        return TokenStatus(configured=False, open_by_choice=env_settings.open_server)
    if not _authorised(request):
        raise AuthenticationError()
    return TokenStatus(configured=True, token=settings.access_token)


@router.post("/token", response_model=TokenIssued)
async def issue_token(request: Request) -> TokenIssued:
    """Mint a token, replacing any existing one.

    Rotation and first issue are the same operation on purpose: a separate "rotate" would be the
    same code behind a second name, and one endpoint means there is no path where a client rotates
    when it meant to create.
    """
    from app.api.exceptions import AuthenticationError

    if not _authorised(request):
        raise AuthenticationError()

    token = generate_token()
    get_app_settings_service().update(access_token=token)
    return TokenIssued(configured=True, token=token)


@router.delete("/token", response_model=TokenStatus)
async def revoke_token(request: Request) -> TokenStatus:
    """Clear the token, returning the server to unauthenticated.

    Kept because a token that cannot be removed is one an operator will work around by editing JSON
    on the NAS — the thing rotation exists to prevent. It reopens the server, which is why it needs
    the current token.
    """
    from app.api.exceptions import AuthenticationError

    if not _authorised(request):
        raise AuthenticationError()

    get_app_settings_service().update(access_token=None)
    return TokenStatus(configured=False)


class PairingInfo(BaseModel):
    """What a pairing link carries (ADR-0134 point 5), for the web admin to render as a QR code.

    The server does not build the link itself, because it does not know how the phone reaches it:
    behind Docker its own addresses are the container's, and behind Tailscale the useful host is a
    name only the operator knows. The web admin knows the host it was loaded from and builds the link
    from that, falling back to `addresses` when that host is loopback.
    """

    server_id: str
    server_name: str
    token: str
    #: The port this server advertises, when it advertises one; otherwise the client uses the port it
    #: already reached the server on.
    port: int | None = None
    #: This machine's LAN addresses, private ranges first.
    addresses: list[str]
    header: str = TOKEN_HEADER


@router.get("/pairing", response_model=PairingInfo)
async def get_pairing(request: Request) -> PairingInfo:
    """Everything a `familiar://pair` link needs. Requires a token, and holding it.

    Pairing hands a client the token, so a server without one has nothing to pair with. That is a
    conflict to resolve (create a token), not an authentication failure.
    """
    from app.api.exceptions import AuthenticationError, ConflictError
    from app.config import settings as env_settings
    from app.services.server_identity import get_server_identity, lan_addresses

    token = get_app_settings_service().get().access_token
    if not token:
        raise ConflictError(
            "This server has no token to pair with",
            detail="Create a server token first: pairing gives a device that token.",
        )
    if not _authorised(request):
        raise AuthenticationError()

    identity = get_server_identity()
    return PairingInfo(
        server_id=identity.server_id,
        server_name=identity.server_name,
        token=token,
        port=env_settings.advertise_port,
        addresses=lan_addresses(),
    )
