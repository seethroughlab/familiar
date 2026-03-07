from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


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
