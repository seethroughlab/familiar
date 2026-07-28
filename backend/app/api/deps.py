"""Dependency injection for API routes."""

from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_maker
from app.utils.time import utcnow

if TYPE_CHECKING:
    from app.db.models import Profile


# The profile header, declared so it reaches the OpenAPI schema (ADR-0007).
#
# Both dependencies below read the header off the raw request and always did. That works at
# runtime and is invisible to the schema: FastAPI only emits a parameter or security scheme for
# things declared as such, so a generated client got methods with no way to pass a profile and no
# hint that the call would 401. ADR-0007's Context called auth "no complexity", which is true of
# the model and beside the point — generation consumes the schema, not the model.
#
# `auto_error=False` is load-bearing: FastAPI must not reject the request itself, because the two
# dependencies have different and deliberate behaviours for a missing header (None vs 401) and the
# error envelope is normalised centrally in main.py.
profile_header = APIKeyHeader(
    name="X-Profile-ID",
    auto_error=False,
    scheme_name="ProfileHeader",
    description=(
        "Profile identity. Obtain one from POST /api/v1/profiles/register. "
        "Optional on some endpoints, required on most; see each operation."
    ),
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get an async database session with proper transaction handling."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_current_profile(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _header: str | None = Depends(profile_header),
) -> "Profile | None":
    """Get profile from X-Profile-ID header.

    The frontend must first register a profile via POST /profiles/register,
    which returns a profile_id. That profile_id should be sent in the
    X-Profile-ID header for all subsequent requests.

    For backwards compatibility, if no header is provided, returns None
    allowing routes to fall back to legacy behavior.

    `_header` is unused deliberately: depending on `profile_header` is what puts the security
    requirement on every operation using this dependency. The value is still read from the raw
    request below so the behaviour is byte-for-byte what it was.
    """
    from app.db.models import Profile

    profile_id_str = request.headers.get("X-Profile-ID")

    if not profile_id_str:
        return None  # Allow fallback to legacy behavior

    try:
        profile_id = UUID(profile_id_str)
    except ValueError:
        raise HTTPException(400, "Invalid profile ID format")

    profile = await db.get(Profile, profile_id)
    if not profile:
        raise HTTPException(401, "Invalid profile ID - please re-register")

    # Update last_seen timestamp (committed by get_db's auto-commit)
    profile.last_seen_at = utcnow()

    return profile


async def require_profile(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _header: str | None = Depends(profile_header),
) -> "Profile":
    """Require a valid profile from X-Profile-ID header.

    Unlike get_current_profile, this raises an error if no profile is provided.
    Use this for endpoints that require a profile.

    See `get_current_profile` for why `_header` is depended on but unused.
    """
    from app.db.models import Profile

    profile_id_str = request.headers.get("X-Profile-ID")

    if not profile_id_str:
        raise HTTPException(401, "Profile ID required - register at POST /profiles/register")

    try:
        profile_id = UUID(profile_id_str)
    except ValueError:
        raise HTTPException(400, "Invalid profile ID format")

    profile = await db.get(Profile, profile_id)
    if not profile:
        raise HTTPException(401, "Invalid profile ID - please re-register")

    # Update last_seen timestamp (committed by get_db's auto-commit)
    profile.last_seen_at = utcnow()

    return profile


# Type aliases for dependency injection
DbSession = Annotated[AsyncSession, Depends(get_db)]
CurrentProfile = Annotated["Profile", Depends(get_current_profile)]
RequiredProfile = Annotated["Profile", Depends(require_profile)]
