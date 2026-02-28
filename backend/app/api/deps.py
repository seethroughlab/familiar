"""Dependency injection for API routes."""

from collections.abc import AsyncGenerator
from datetime import datetime
from app.utils.time import utcnow
from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_maker

if TYPE_CHECKING:
    from app.db.models import Profile


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
) -> "Profile | None":
    """Get profile from X-Profile-ID header.

    The frontend must first register a profile via POST /profiles/register,
    which returns a profile_id. That profile_id should be sent in the
    X-Profile-ID header for all subsequent requests.

    For backwards compatibility, if no header is provided, returns None
    allowing routes to fall back to legacy behavior.
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
) -> "Profile":
    """Require a valid profile from X-Profile-ID header.

    Unlike get_current_profile, this raises an error if no profile is provided.
    Use this for endpoints that require a profile.
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
