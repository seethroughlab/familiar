"""Profile management endpoints for Netflix-style multi-user support."""

import io
import logging
from uuid import UUID

from fastapi import APIRouter, UploadFile, status
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DbSession, RequiredProfile
from app.api.exceptions import (
    NotFoundError,
    PayloadTooLargeError,
    ProfileNotFoundError,
    ValidationError,
)
from app.config import settings
from app.db.models import Profile
from app.utils.time import to_rfc3339

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/profiles", tags=["profiles"])

# Ensure profiles directory exists
PROFILES_DIR = settings.profiles_path
PROFILES_DIR.mkdir(parents=True, exist_ok=True)

MAX_AVATAR_SIZE = 5 * 1024 * 1024  # 5MB
AVATAR_SIZE = 256  # Output size in pixels


class ProfileCreate(BaseModel):
    """Request to create a new profile."""

    name: str = Field(..., min_length=1, max_length=100)
    color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")


class ProfileUpdate(BaseModel):
    """Request to update a profile."""

    name: str | None = Field(None, min_length=1, max_length=100)
    color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")


class ProfileResponse(BaseModel):
    """Profile response."""

    id: UUID
    name: str
    color: str | None
    avatar_url: str | None
    created_at: str
    has_lastfm: bool


def profile_to_response(profile: Profile, has_lastfm: bool) -> ProfileResponse:
    """Convert Profile model to response."""
    avatar_url = None
    if profile.avatar_path:
        avatar_url = f"/api/v1/profiles/{profile.id}/avatar"

    return ProfileResponse(
        id=profile.id,
        name=profile.name,
        color=profile.color,
        avatar_url=avatar_url,
        created_at=to_rfc3339(profile.created_at),
        has_lastfm=has_lastfm,
    )


@router.get("", response_model=list[ProfileResponse])
async def list_profiles(db: DbSession) -> list[ProfileResponse]:
    """List all profiles.

    Used by the profile selector screen to show available profiles.
    """
    result = await db.execute(
        select(Profile).order_by(Profile.name)
    )
    profiles = result.scalars().all()

    responses = []
    for profile in profiles:
        await db.refresh(profile, ["lastfm_profile"])
        has_lastfm = profile.lastfm_profile is not None
        responses.append(profile_to_response(profile, has_lastfm))

    return responses


@router.post("", response_model=ProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_profile(
    request: ProfileCreate,
    db: DbSession,
) -> ProfileResponse:
    """Create a new profile.

    Returns the new profile's ID which should be stored locally
    and sent in X-Profile-ID header for all subsequent requests.
    """
    profile = Profile(
        name=request.name,
        color=request.color,
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)

    return profile_to_response(profile, has_lastfm=False)


@router.get("/me", response_model=ProfileResponse)
async def get_current_profile_info(
    profile: RequiredProfile,
    db: DbSession,
) -> ProfileResponse:
    """Get current profile info.

    Requires X-Profile-ID header.
    """
    await db.refresh(profile, ["lastfm_profile"])
    has_lastfm = profile.lastfm_profile is not None

    return profile_to_response(profile, has_lastfm)


@router.get("/{profile_id}", response_model=ProfileResponse)
async def get_profile(
    profile_id: UUID,
    db: DbSession,
) -> ProfileResponse:
    """Get a profile by ID."""
    profile = await db.get(Profile, profile_id)
    if not profile:
        raise ProfileNotFoundError()

    await db.refresh(profile, ["lastfm_profile"])
    has_lastfm = profile.lastfm_profile is not None

    return profile_to_response(profile, has_lastfm)


@router.put("/{profile_id}", response_model=ProfileResponse)
async def update_profile(
    profile_id: UUID,
    request: ProfileUpdate,
    db: DbSession,
) -> ProfileResponse:
    """Update a profile."""
    profile = await db.get(Profile, profile_id)
    if not profile:
        raise ProfileNotFoundError()

    update_data = request.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(profile, key, value)

    await db.commit()
    await db.refresh(profile, ["lastfm_profile"])

    has_lastfm = profile.lastfm_profile is not None

    return profile_to_response(profile, has_lastfm)


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile(
    profile_id: UUID,
    db: DbSession,
) -> None:
    """Delete a profile and all associated data."""
    profile = await db.get(Profile, profile_id)
    if not profile:
        raise ProfileNotFoundError()

    # Delete avatar file if it exists
    if profile.avatar_path:
        avatar_file = PROFILES_DIR / f"{profile.id}.jpg"
        if avatar_file.exists():
            avatar_file.unlink()

    await db.delete(profile)
    await db.commit()


def crop_to_square(img: Image.Image) -> Image.Image:
    """Center-crop image to square."""
    width, height = img.size
    size = min(width, height)
    left = (width - size) // 2
    top = (height - size) // 2
    return img.crop((left, top, left + size, top + size))


@router.post("/{profile_id}/avatar", response_model=ProfileResponse)
async def upload_avatar(
    profile_id: UUID,
    file: UploadFile,
    db: DbSession,
) -> ProfileResponse:
    """Upload a profile avatar image.

    The image will be center-cropped to a square and resized to 256x256.
    Accepts JPEG, PNG, WebP, or GIF formats.
    """
    profile = await db.get(Profile, profile_id)
    if not profile:
        raise ProfileNotFoundError()

    # Validate file size
    contents = await file.read()
    if len(contents) > MAX_AVATAR_SIZE:
        raise PayloadTooLargeError("Image too large. Maximum size is 5MB.")

    # Validate and process image
    try:
        img: Image.Image = Image.open(io.BytesIO(contents))

        # Convert to RGB (handles RGBA, palette, etc.)
        if img.mode in ("RGBA", "LA", "P"):
            # Create white background for transparent images
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            background.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # Center-crop to square
        img = crop_to_square(img)

        # Resize to target size
        img = img.resize((AVATAR_SIZE, AVATAR_SIZE), Image.Resampling.LANCZOS)

        # Save as JPEG
        avatar_path = PROFILES_DIR / f"{profile_id}.jpg"
        img.save(avatar_path, "JPEG", quality=85)

        # Update profile
        profile.avatar_path = f"profiles/{profile_id}.jpg"
        await db.commit()

        logger.info(f"Avatar uploaded for profile {profile_id}")

    except Exception as e:
        logger.error(f"Failed to process avatar: {e}")
        raise ValidationError("Invalid image file. Please upload a JPEG, PNG, WebP, or GIF.")

    await db.refresh(profile, ["lastfm_profile"])
    has_lastfm = profile.lastfm_profile is not None

    return profile_to_response(profile, has_lastfm)


@router.get(
    "/{profile_id}/avatar",
    response_class=FileResponse,
    responses={200: {"content": {"image/*": {}}, "description": "Profile avatar image."}},
)
async def get_avatar(
    profile_id: UUID,
    db: DbSession,
) -> FileResponse:
    """Get a profile's avatar image."""
    profile = await db.get(Profile, profile_id)
    if not profile:
        raise ProfileNotFoundError()

    if not profile.avatar_path:
        raise NotFoundError("Profile has no avatar")

    avatar_file = PROFILES_DIR / f"{profile_id}.jpg"
    if not avatar_file.exists():
        raise NotFoundError("Avatar file not found")

    return FileResponse(
        avatar_file,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},  # Cache for 1 day
    )


@router.delete("/{profile_id}/avatar", response_model=ProfileResponse)
async def delete_avatar(
    profile_id: UUID,
    db: DbSession,
) -> ProfileResponse:
    """Delete a profile's avatar image."""
    profile = await db.get(Profile, profile_id)
    if not profile:
        raise ProfileNotFoundError()

    if profile.avatar_path:
        avatar_file = PROFILES_DIR / f"{profile_id}.jpg"
        if avatar_file.exists():
            avatar_file.unlink()
        profile.avatar_path = None
        await db.commit()

    await db.refresh(profile, ["lastfm_profile"])
    has_lastfm = profile.lastfm_profile is not None

    return profile_to_response(profile, has_lastfm)
