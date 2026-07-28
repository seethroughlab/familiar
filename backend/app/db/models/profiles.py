from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
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


class PlaybackSessionPayload:
    """The queue itself, shared by the live session and its archive.

    A declarative mixin rather than two copies, so the two tables cannot drift: an
    archived row has to be able to replace a live one field for field, and a column added
    to only one of them would surface as a restore-time failure rather than an error at
    import.
    """

    # Track IDs as JSONB rather than ARRAY(UUID): every other list-of-IDs column in this
    # schema is JSONB (see MixTape.track_ids), and nothing queries into them.
    track_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # Index of the current track; -1 when the queue is empty.
    cursor: Mapped[int] = mapped_column(Integer, nullable=False, default=-1)
    shuffle_order: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=list)
    shuffle_index: Mapped[int] = mapped_column(Integer, nullable=False, default=-1)
    shuffle: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 'off' | 'all' | 'one'
    repeat: Mapped[str] = mapped_column(String(8), nullable=False, default="off")
    consume: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # {type, id?, filters?} — stored whole rather than decomposed into columns, because
    # toggleShuffle replays `filters` verbatim against the library. `type` uses the
    # client's queue-source vocabulary, which is narrower than PlayContext: 'radio' and
    # 'ambient' are listening contexts, not queue sources (ADR-0003 point 8).
    queue_source: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # The lazy reservoir: the full ID list a library queue draws from, of which only a
    # ~50-track window is materialised in `track_ids`. Without it a restored queue
    # silently ends after that window.
    reservoir_ids: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    reservoir_cursor: Mapped[int] = mapped_column(Integer, nullable=False, default=-1)
    # Lets a client omit `reservoir_ids` on a write when it has not changed, instead of
    # shipping ~1 MB of UUIDs with every cursor advance (ADR-0003 point 4).
    reservoir_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Position within the current track. Without it a handoff resumes at the top of the
    # track rather than where the listener actually was.
    position_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class PlaybackSession(PlaybackSessionPayload, Base):
    """The durable playback queue for a profile — one row, the server's source of truth.

    Keyed by profile alone, with no device dimension (ADR-0003 point 1). One live queue
    per profile means picking up another device continues what the first was playing with
    no explicit transfer step, and it avoids inventing a device identity the codebase does
    not have: `Profile.device_id` is a legacy column with no readers, and the client-side
    `deviceId` is written as the empty string.

    The cost, accepted deliberately: two devices playing at once under one profile contend
    over the cursor, and the one that writes later wins.

    Clients hold an authoritative local replica and never block playback on this. What
    they send is always the *logical* queue, never a queue narrowed to downloaded tracks —
    uploading a narrowed queue would overwrite every other device's copy with whatever
    this one happened to have offline.
    """

    __tablename__ = "playback_sessions"

    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True
    )

    # Bumped on every accepted write, so a client can tell whether the session it holds
    # is the one the server has.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Decides conflicts: the later write wins. `onupdate` is applied by the ORM, so
    # writes must go through the ORM — a bulk `update()` would leave this stale and
    # silently freeze the conflict rule.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PlaybackSessionArchive(PlaybackSessionPayload, Base):
    """A superseded queue, kept so a lost conflict is recoverable.

    ADR-0003 point 6: the later write wins, but the loser is never destroyed. Two devices
    that diverged while offline both built something the listener may want back, and
    silently discarding one is the failure the conflict rule exists to avoid.

    Bounded per profile — see ARCHIVE_LIMIT in the queue routes — since the alternative
    is unbounded growth of queues nobody will ask for.
    """

    __tablename__ = "playback_session_archive"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )

    # When the superseded session was last written by the device that built it — not when
    # it was archived, which would lose the only clue about which queue this was.
    superseded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    archived_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # Listing a profile's restorable queues, newest first.
        Index("ix_playback_session_archive_profile", "profile_id", "archived_at"),
    )
