from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Playlist(Base):
    """User-created or AI-generated playlists."""

    __tablename__ = "playlists"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_auto_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    is_wishlist: Mapped[bool] = mapped_column(Boolean, default=False)  # Special system playlist
    generation_prompt: Mapped[str | None] = mapped_column(Text)
    auto_download: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    profile: Mapped["Profile"] = relationship(back_populates="playlists")
    tracks: Mapped[list["PlaylistTrack"]] = relationship(
        back_populates="playlist", cascade="all, delete"
    )


class PlaylistTrack(Base):
    """Junction table for playlist tracks with ordering.

    Supports both local tracks and external/missing tracks.
    Exactly one of track_id or external_track_id must be set.
    """

    __tablename__ = "playlist_tracks"
    __table_args__ = (
        CheckConstraint(
            "(track_id IS NOT NULL AND external_track_id IS NULL) OR "
            "(track_id IS NULL AND external_track_id IS NOT NULL)",
            name="ck_playlist_track_exactly_one_ref",
        ),
        Index("ix_playlist_tracks_playlist", "playlist_id"),
        Index("ix_playlist_tracks_track", "track_id"),
        Index("ix_playlist_tracks_external", "external_track_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    playlist_id: Mapped[UUID] = mapped_column(
        ForeignKey("playlists.id", ondelete="CASCADE"), nullable=False
    )
    track_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tracks.id", ondelete="CASCADE")
    )
    external_track_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("external_tracks.id", ondelete="CASCADE")
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    playlist: Mapped["Playlist"] = relationship(back_populates="tracks")
    track: Mapped["Track | None"] = relationship(back_populates="playlist_entries")
    external_track: Mapped["ExternalTrack | None"] = relationship(back_populates="playlist_entries")


class SmartPlaylist(Base):
    """Rule-based auto-updating playlists."""

    __tablename__ = "smart_playlists"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # Rules stored as JSONB for flexibility
    # Example: [
    #   {"field": "genre", "operator": "contains", "value": "electronic"},
    #   {"field": "bpm", "operator": "between", "value": [120, 140]},
    #   {"field": "energy", "operator": ">=", "value": 0.7},
    #   {"field": "is_favorite", "operator": "=", "value": true},
    #   {"field": "play_count", "operator": ">=", "value": 5}
    # ]
    rules: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    # Rule matching mode: "all" (AND) or "any" (OR)
    match_mode: Mapped[str] = mapped_column(String(10), default="all")

    # Ordering
    order_by: Mapped[str] = mapped_column(String(50), default="title")
    order_direction: Mapped[str] = mapped_column(String(4), default="asc")

    # Limits
    max_tracks: Mapped[int | None] = mapped_column(Integer)

    # Cache
    cached_track_count: Mapped[int] = mapped_column(Integer, default=0)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime)

    auto_download: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    profile: Mapped["Profile"] = relationship(back_populates="smart_playlists")
