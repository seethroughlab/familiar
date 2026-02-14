from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Profile(Base):
    """Selectable profile for multi-user support (Netflix-style).

    Profiles can be selected from any device. No authentication required.
    Each profile has its own playlists, favorites, play history, and service connections.
    """

    __tablename__ = "profiles"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    color: Mapped[str | None] = mapped_column(String(7))  # Hex color like "#3B82F6"
    avatar_path: Mapped[str | None] = mapped_column(String(255))  # e.g. "profiles/abc123.jpg"
    device_id: Mapped[str | None] = mapped_column(String(64))  # Legacy, no longer required
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    # Relationships
    spotify_profile: Mapped["SpotifyProfile | None"] = relationship(
        back_populates="profile", cascade="all, delete"
    )
    lastfm_profile: Mapped["LastfmProfile | None"] = relationship(
        back_populates="profile", cascade="all, delete"
    )
    subsonic_credentials: Mapped[list["SubsonicCredential"]] = relationship(
        back_populates="profile", cascade="all, delete"
    )
    playlists: Mapped[list["Playlist"]] = relationship(
        back_populates="profile", cascade="all, delete"
    )
    smart_playlists: Mapped[list["SmartPlaylist"]] = relationship(
        back_populates="profile", cascade="all, delete"
    )
    favorites: Mapped[list["ProfileFavorite"]] = relationship(
        back_populates="profile", cascade="all, delete"
    )
    external_favorites: Mapped[list["ProfileExternalFavorite"]] = relationship(
        back_populates="profile", cascade="all, delete"
    )
    play_history: Mapped[list["ProfilePlayHistory"]] = relationship(
        back_populates="profile", cascade="all, delete"
    )


class LastfmProfile(Base):
    """Last.fm session storage per profile.

    Persists the Last.fm session key so it survives server restarts.
    Previously this was stored in-memory and lost on restart.
    """

    __tablename__ = "lastfm_profiles"

    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True
    )
    username: Mapped[str | None] = mapped_column(String(255))
    session_key: Mapped[str | None] = mapped_column(String(255))
    connected_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    profile: Mapped["Profile"] = relationship(back_populates="lastfm_profile")


class SubsonicCredential(Base):
    """Subsonic API credentials mapped to a Familiar profile.

    Stores both bcrypt hash (for direct password auth) and plaintext password
    (for Subsonic token auth which requires md5(password+salt) verification).
    The password is auto-generated random string, not user-chosen.
    """

    __tablename__ = "subsonic_credentials"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))  # bcrypt for direct auth
    password_token: Mapped[str] = mapped_column(String(255))  # plaintext for token auth
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    profile: Mapped["Profile"] = relationship(back_populates="subsonic_credentials")


class SpotifyProfile(Base):
    """Spotify OAuth tokens per device profile.

    Linked to Profile for device-based multi-user support.
    """

    __tablename__ = "spotify_profiles"

    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True
    )
    spotify_user_id: Mapped[str | None] = mapped_column(String(255))
    access_token: Mapped[str | None] = mapped_column(Text)
    refresh_token: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    sync_mode: Mapped[str] = mapped_column(String(20), default="periodic")
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    # Relationships
    profile: Mapped["Profile"] = relationship(back_populates="spotify_profile")
    favorites: Mapped[list["SpotifyFavorite"]] = relationship(
        back_populates="spotify_profile", cascade="all, delete"
    )


class SpotifyFavorite(Base):
    """Synced Spotify favorites per device profile."""

    __tablename__ = "spotify_favorites"
    __table_args__ = (
        UniqueConstraint("profile_id", "spotify_track_id", name="uq_spotify_favorite_profile"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("spotify_profiles.profile_id", ondelete="CASCADE"))
    spotify_track_id: Mapped[str] = mapped_column(String(255), nullable=False)
    matched_track_id: Mapped[UUID | None] = mapped_column(ForeignKey("tracks.id", ondelete="SET NULL"))

    # Spotify track data (JSONB for flexibility)
    track_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    added_at: Mapped[datetime | None] = mapped_column(DateTime)
    synced_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    spotify_profile: Mapped["SpotifyProfile"] = relationship(back_populates="favorites")
    matched_track: Mapped["Track | None"] = relationship()


class ProfileFavorite(Base):
    """Track favorites per profile (local, not Spotify)."""

    __tablename__ = "profile_favorites"

    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True
    )
    track_id: Mapped[UUID] = mapped_column(
        ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True
    )
    favorited_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    profile: Mapped["Profile"] = relationship(back_populates="favorites")
    track: Mapped["Track"] = relationship()


class ProfileExternalFavorite(Base):
    """External track favorites per profile (tracks not in local library)."""

    __tablename__ = "profile_external_favorites"
    __table_args__ = (
        UniqueConstraint("profile_id", "external_track_id", name="uq_profile_external_favorite"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    external_track_id: Mapped[UUID] = mapped_column(
        ForeignKey("external_tracks.id", ondelete="CASCADE"), index=True
    )
    favorited_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    profile: Mapped["Profile"] = relationship(back_populates="external_favorites")
    external_track: Mapped["ExternalTrack"] = relationship()


class ProfilePlayHistory(Base):
    """Aggregated play history per profile with counts."""

    __tablename__ = "profile_play_history"

    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True
    )
    track_id: Mapped[UUID] = mapped_column(
        ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True
    )
    play_count: Mapped[int] = mapped_column(Integer, default=0)
    last_played_at: Mapped[datetime | None] = mapped_column(DateTime)
    total_play_seconds: Mapped[float] = mapped_column(Float, default=0.0)

    # Relationships
    profile: Mapped["Profile"] = relationship(back_populates="play_history")
    track: Mapped["Track"] = relationship()
