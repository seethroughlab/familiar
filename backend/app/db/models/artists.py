from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
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


class ArtistCheckCache(Base):
    """Tracks when each library artist was last checked for new releases.

    Scoped to the new-releases background task (#3 surface). Holds polling
    cadence + priority, not album records.
    """

    __tablename__ = "artist_check_cache"

    artist_name_normalized: Mapped[str] = mapped_column(String(500), primary_key=True)
    musicbrainz_artist_id: Mapped[str | None] = mapped_column(String(36))
    last_checked_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Priority-based checking
    check_priority: Mapped[float] = mapped_column(Float, default=0.0)
    priority_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ExternalAlbumCache(Base):
    """Cache of external albums (not in the local library) discovered for the user.

    Shared by the new-releases surface (#3, ``discovery_context='artist_new_release'``)
    and the playlist-context external recommendations surface (#2,
    ``discovery_context='playlist_recommendation'``, added in a later pass).
    """

    __tablename__ = "external_album_cache"
    __table_args__ = (
        # Partial unique indexes: same release_id can appear once per #3,
        # once per (#2, playlist), and once per listening-profile #2.
        Index(
            "ix_eac_artist_new_release_unique",
            "release_id",
            unique=True,
            postgresql_where=Text("discovery_context = 'artist_new_release'"),
        ),
        Index(
            "ix_eac_playlist_rec_unique",
            "release_id",
            "source_playlist_id",
            unique=True,
            postgresql_where=Text("discovery_context = 'playlist_recommendation'"),
        ),
        Index(
            "ix_eac_listening_profile_unique",
            "release_id",
            unique=True,
            postgresql_where=Text(
                "discovery_context = 'listening_profile_recommendation'"
            ),
        ),
        # Compound index for the per-playlist listing query.
        Index(
            "ix_eac_source_playlist_context",
            "source_playlist_id",
            "discovery_context",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    # External release identification (MusicBrainz release-group id today).
    # Uniqueness is enforced via partial unique indexes per discovery_context
    # (see migration 20260427_ext_album_pl), not as a column constraint.
    release_id: Mapped[str] = mapped_column(String(100), nullable=False)
    discovery_context: Mapped[str] = mapped_column(String(40), nullable=False, index=True)

    # For discovery_context='playlist_recommendation', tracks which playlist
    # generated this recommendation. NULL for 'artist_new_release'. The
    # ``ix_eac_source_playlist_context`` compound index handles lookups.
    source_playlist_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("playlists.id", ondelete="CASCADE"),
        nullable=True,
    )

    # Artist
    artist_name: Mapped[str] = mapped_column(String(500), nullable=False)
    artist_name_normalized: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    musicbrainz_artist_id: Mapped[str | None] = mapped_column(String(36))

    # Release metadata
    release_name: Mapped[str] = mapped_column(String(500), nullable=False)
    release_type: Mapped[str | None] = mapped_column(String(20))  # album, single, ep
    release_date: Mapped[datetime | None] = mapped_column(DateTime)
    artwork_url: Mapped[str | None] = mapped_column(String(500))
    external_url: Mapped[str | None] = mapped_column(String(500))
    track_count: Mapped[int | None] = mapped_column(Integer)
    extra_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    # Per-profile state
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    dismissed_by_profile_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="SET NULL")
    )
    local_album_match: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    discovered_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
