from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ArtistCheckCache(Base):
    """Cache for tracking when artists were last checked for new releases."""

    __tablename__ = "artist_check_cache"

    artist_name_normalized: Mapped[str] = mapped_column(String(500), primary_key=True)
    musicbrainz_artist_id: Mapped[str | None] = mapped_column(String(36))
    spotify_artist_id: Mapped[str | None] = mapped_column(String(50))
    last_checked_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Priority-based checking fields
    check_priority: Mapped[float] = mapped_column(Float, default=0.0)
    priority_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ArtistNewRelease(Base):
    """Cached new releases discovered from external APIs."""

    __tablename__ = "artist_new_releases"
    __table_args__ = (
        UniqueConstraint("source", "release_id", name="uq_artist_new_release"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    # Artist identification
    artist_name: Mapped[str] = mapped_column(String(500), nullable=False)
    artist_name_normalized: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    musicbrainz_artist_id: Mapped[str | None] = mapped_column(String(36))
    spotify_artist_id: Mapped[str | None] = mapped_column(String(50))

    # Release identification
    release_id: Mapped[str] = mapped_column(String(100), nullable=False)  # External ID
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # "spotify" or "musicbrainz"

    # Release metadata
    release_name: Mapped[str] = mapped_column(String(500), nullable=False)
    release_type: Mapped[str | None] = mapped_column(String(20))  # album, single, ep
    release_date: Mapped[datetime | None] = mapped_column(DateTime)
    artwork_url: Mapped[str | None] = mapped_column(String(500))
    external_url: Mapped[str | None] = mapped_column(String(500))
    track_count: Mapped[int | None] = mapped_column(Integer)
    extra_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    # Status flags
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)
    dismissed_by_profile_id: Mapped[UUID | None] = mapped_column(ForeignKey("profiles.id", ondelete="SET NULL"))
    local_album_match: Mapped[bool] = mapped_column(Boolean, default=False)  # Already in library

    # Timestamps
    discovered_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ArtistInfo(Base):
    """Cached artist information from Last.fm API.

    Stores bio, images, and metadata to avoid repeated API calls.
    Cache expires after 30 days.
    """

    __tablename__ = "artist_info"

    # Primary key is normalized artist name (lowercase, stripped)
    artist_name_normalized: Mapped[str] = mapped_column(String(500), primary_key=True)

    # Display name (original casing from Last.fm)
    artist_name: Mapped[str] = mapped_column(String(500), nullable=False)

    # External IDs
    musicbrainz_id: Mapped[str | None] = mapped_column(String(36))
    lastfm_url: Mapped[str | None] = mapped_column(String(500))

    # Bio content
    bio_summary: Mapped[str | None] = mapped_column(Text)  # Short bio
    bio_content: Mapped[str | None] = mapped_column(Text)  # Full bio

    # Images (store URLs - Last.fm provides multiple sizes)
    image_small: Mapped[str | None] = mapped_column(String(500))
    image_medium: Mapped[str | None] = mapped_column(String(500))
    image_large: Mapped[str | None] = mapped_column(String(500))
    image_extralarge: Mapped[str | None] = mapped_column(String(500))

    # Stats from Last.fm
    listeners: Mapped[int | None] = mapped_column(Integer)
    playcount: Mapped[int | None] = mapped_column(BigInteger)

    # Similar artists (stored as JSONB list)
    similar_artists: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    # Tags (stored as JSONB list)
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list)

    # Cache management
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    fetch_error: Mapped[str | None] = mapped_column(String(500))  # Store error if fetch failed
