from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
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
    lastfm_profile: Mapped["LastfmProfile | None"] = relationship(
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
    play_history: Mapped[list["ProfilePlayHistory"]] = relationship(
        back_populates="profile", cascade="all, delete"
    )
    play_events: Mapped[list["PlayEvent"]] = relationship(
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


class PlayEvent(Base):
    """One row per listening event — the per-play log behind ProfilePlayHistory.

    ProfilePlayHistory aggregates (play_count, summed total_play_seconds) and so cannot
    distinguish a track played once in full from one skipped twenty times at three seconds.
    This table keeps each play intact so completion and skips stay recoverable.

    Written alongside ProfilePlayHistory, which keeps its existing semantics: only a
    'completed' event bumps the aggregate. Skips and rejections are recorded here only.
    """

    __tablename__ = "play_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    track_id: Mapped[UUID] = mapped_column(
        ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False
    )
    # The track this one was suggested from (radio insertion); NULL for ordinary plays
    source_track_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tracks.id", ondelete="SET NULL")
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    played_seconds: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # Duration as known by the client at play time; NULL when unavailable
    track_duration: Mapped[float | None] = mapped_column(Float)
    completion_ratio: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # 'completed' | 'skipped' | 'rejected' | 'errored'
    # 'errored' means playback failed, NOT that the listener disliked it — it must never
    # be used as a negative taste signal.
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    # 'library' | 'album' | 'playlist' | 'artist' | 'ephemeral' | 'radio' | 'ambient' | 'other'
    context: Mapped[str | None] = mapped_column(String(16))

    __table_args__ = (
        # Recent-history scans for a profile
        Index("ix_play_events_profile_started_at", "profile_id", "started_at"),
        # Per-candidate feedback lookup when ranking (profile + track)
        Index("ix_play_events_profile_track", "profile_id", "track_id"),
        # Supports the ON DELETE CASCADE from tracks
        Index("ix_play_events_track_id", "track_id"),
    )

    # Relationships
    profile: Mapped["Profile"] = relationship(back_populates="play_events")
    # Explicit foreign_keys: two FKs point at tracks.id (track_id and source_track_id)
    track: Mapped["Track"] = relationship(foreign_keys=[track_id])
