"""Subsonic credential management API.

Used by the Settings UI to generate/view/delete Subsonic API credentials.
These credentials allow Subsonic-compatible apps (Symfonium, play:Sub, etc.)
to connect to Familiar.
"""

import secrets

import bcrypt
from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import DbSession, RequiredProfile
from app.db.models import SubsonicCredential

router = APIRouter(prefix="/subsonic", tags=["subsonic-admin"])


@router.get("/credentials")
async def get_credentials(db: DbSession, profile: RequiredProfile):
    """Get Subsonic credential status for current profile."""
    result = await db.execute(
        select(SubsonicCredential).where(SubsonicCredential.profile_id == profile.id)
    )
    cred = result.scalar_one_or_none()
    if not cred:
        return {"configured": False}
    return {
        "configured": True,
        "username": cred.username,
        "created_at": cred.created_at.isoformat(),
    }


@router.post("/credentials")
async def create_credentials(db: DbSession, profile: RequiredProfile):
    """Generate new Subsonic credentials for current profile.

    Returns the password once — it cannot be retrieved again (only regenerated).
    """
    # Delete existing credential for this profile
    existing = await db.execute(
        select(SubsonicCredential).where(SubsonicCredential.profile_id == profile.id)
    )
    for cred in existing.scalars().all():
        await db.delete(cred)
    await db.flush()

    # Generate username from profile name
    username = profile.name.lower().replace(" ", "_")
    base_username = username
    counter = 1
    while True:
        check = await db.execute(
            select(SubsonicCredential).where(SubsonicCredential.username == username)
        )
        if not check.scalar_one_or_none():
            break
        username = f"{base_username}{counter}"
        counter += 1

    password = secrets.token_urlsafe(16)

    cred = SubsonicCredential(
        profile_id=profile.id,
        username=username,
        password_hash=bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
        password_token=password,
    )
    db.add(cred)
    await db.flush()

    return {
        "configured": True,
        "username": username,
        "password": password,  # Shown once to the user
    }


@router.delete("/credentials")
async def delete_credentials(db: DbSession, profile: RequiredProfile):
    """Delete Subsonic credentials for current profile."""
    result = await db.execute(
        select(SubsonicCredential).where(SubsonicCredential.profile_id == profile.id)
    )
    for cred in result.scalars().all():
        await db.delete(cred)
    return {"configured": False}
