from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import AlbumType, Base, ExternalTrackSource, TrackStatus


class Track(Base):
    """Core track entity with metadata from file tags."""

    __tablename__ = "tracks"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    file_path: Mapped[str] = mapped_column(String(1000), unique=True, nullable=False)
    # Partial hash (first/last 8KB + size) for fast change detection; see compute_file_hash()
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    full_file_hash: Mapped[str | None] = mapped_column(String(64))
    file_size: Mapped[int | None] = mapped_column(BigInteger)

    # Basic metadata from tags (indexed for common queries)
    title: Mapped[str | None] = mapped_column(String(500))
    artist: Mapped[str | None] = mapped_column(String(500), index=True)
    album: Mapped[str | None] = mapped_column(String(500), index=True)
    album_artist: Mapped[str | None] = mapped_column(String(500))
    album_type: Mapped[AlbumType] = mapped_column(Enum(AlbumType), default=AlbumType.ALBUM)
    track_number: Mapped[int | None] = mapped_column(Integer)
    disc_number: Mapped[int | None] = mapped_column(Integer)
    year: Mapped[int | None] = mapped_column(Integer, index=True)
    genre: Mapped[str | None] = mapped_column(String(255), index=True)

    # Technical metadata
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    sample_rate: Mapped[int | None] = mapped_column(Integer)
    bit_depth: Mapped[int | None] = mapped_column(Integer)
    bitrate: Mapped[int | None] = mapped_column(Integer)
    bitrate_mode: Mapped[str | None] = mapped_column(String(10))  # "CBR", "VBR", or None
    format: Mapped[str | None] = mapped_column(String(10))

    # External IDs (from MusicBrainz, etc.)
    musicbrainz_track_id: Mapped[str | None] = mapped_column(String(36))
    musicbrainz_artist_id: Mapped[str | None] = mapped_column(String(36))
    musicbrainz_album_id: Mapped[str | None] = mapped_column(String(36))
    isrc: Mapped[str | None] = mapped_column(String(12))

    # Extended metadata (for editing)
    composer: Mapped[str | None] = mapped_column(String(500))
    conductor: Mapped[str | None] = mapped_column(String(500))
    lyricist: Mapped[str | None] = mapped_column(String(500))
    grouping: Mapped[str | None] = mapped_column(String(255))
    comment: Mapped[str | None] = mapped_column(Text)

    # Sort fields (for proper alphabetization)
    sort_artist: Mapped[str | None] = mapped_column(String(500))
    sort_album: Mapped[str | None] = mapped_column(String(500))
    sort_title: Mapped[str | None] = mapped_column(String(500))

    # Embedded lyrics
    lyrics: Mapped[str | None] = mapped_column(Text)

    # User overrides for auto-detected analysis values
    # Example: {"bpm": 124.0, "key": "Am"} - overrides analysis.features values
    user_overrides: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    # Analysis status
    analysis_version: Mapped[int] = mapped_column(Integer, default=0)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime)
    analysis_error: Mapped[str | None] = mapped_column(String(500))
    analysis_failed_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Timestamps
    file_modified_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # File availability status (prevents catastrophic deletion)
    status: Mapped[TrackStatus] = mapped_column(
        Enum(TrackStatus, values_callable=lambda obj: [e.value for e in obj]),
        default=TrackStatus.ACTIVE,
        index=True,
    )
    missing_since: Mapped[datetime | None] = mapped_column(DateTime)  # When file was first not found

    # Relationships
    analyses: Mapped[list["TrackAnalysis"]] = relationship(
        back_populates="track", cascade="all, delete"
    )
    playlist_entries: Mapped[list["PlaylistTrack"]] = relationship(
        back_populates="track", cascade="all, delete"
    )


class ExternalTrack(Base):
    """External/missing track that the user wants but doesn't have locally.

    First-class citizens in playlists, appearing alongside local tracks.
    When a matching local track is added to the library, it auto-links via matched_track_id.

    Sources include Spotify imports, LLM recommendations, and manual additions.
    """

    __tablename__ = "external_tracks"
    __table_args__ = (
        Index("ix_external_tracks_artist", "artist"),
        Index("ix_external_tracks_isrc", "isrc"),
        Index("ix_external_tracks_spotify_id", "spotify_id"),
        Index("ix_external_tracks_matched", "matched_track_id"),
        Index("ix_external_tracks_source", "source"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    # Core metadata for display and matching
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    artist: Mapped[str] = mapped_column(String(500), nullable=False)
    album: Mapped[str | None] = mapped_column(String(500))
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    track_number: Mapped[int | None] = mapped_column(Integer)
    year: Mapped[int | None] = mapped_column(Integer)

    # External identifiers for matching
    isrc: Mapped[str | None] = mapped_column(String(12))
    spotify_id: Mapped[str | None] = mapped_column(String(50), unique=True)
    musicbrainz_recording_id: Mapped[str | None] = mapped_column(String(36))
    deezer_id: Mapped[str | None] = mapped_column(String(50))

    # Extended data (album art URLs, external URLs, etc.)
    external_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    # Provenance
    source: Mapped[ExternalTrackSource] = mapped_column(
        Enum(ExternalTrackSource, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    source_playlist_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("playlists.id", ondelete="SET NULL")
    )
    source_spotify_playlist_id: Mapped[str | None] = mapped_column(String(50))

    # Matching status - links to local library track when matched
    matched_track_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tracks.id", ondelete="SET NULL")
    )
    matched_at: Mapped[datetime | None] = mapped_column(DateTime)
    match_confidence: Mapped[float | None] = mapped_column(Float)  # 0.0-1.0
    match_method: Mapped[str | None] = mapped_column(String(20))  # "isrc", "exact", "fuzzy", "manual"

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    matched_track: Mapped["Track | None"] = relationship()
    source_playlist: Mapped["Playlist | None"] = relationship()
    playlist_entries: Mapped[list["PlaylistTrack"]] = relationship(
        back_populates="external_track", cascade="all, delete"
    )


class TrackAnalysis(Base):
    """Versioned audio analysis with JSONB features and vector embedding."""

    __tablename__ = "track_analysis"
    __table_args__ = (UniqueConstraint("track_id", "version", name="uq_track_analysis_version"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    track_id: Mapped[UUID] = mapped_column(ForeignKey("tracks.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    # Flexible features stored as JSONB (no migrations needed when adding new features)
    # Example: {"bpm": 124.5, "key": "Am", "energy": 0.87, "valence": 0.65, ...}
    features: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    # Vector embedding for similarity search (CLAP produces 512-dim embeddings)
    embedding: Mapped[Any | None] = mapped_column(Vector(512))

    # Audio fingerprint for identification (base64-encoded, can be very long)
    acoustid: Mapped[str | None] = mapped_column(Text)

    # Cached AcoustID API lookup results (list of candidates with scores/recording IDs)
    # Avoids repeated API calls for tracks we've already identified
    acoustid_lookup: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # Source tracking: "local", "reccobeats", "community_cache", etc.
    features_source: Mapped[str | None] = mapped_column(String(50))
    embedding_source: Mapped[str | None] = mapped_column(String(50))

    # Embedding failure tracking (separate from Track.analysis_error which is for features)
    embedding_error: Mapped[str | None] = mapped_column(String(500))
    embedding_failed_at: Mapped[datetime | None] = mapped_column(DateTime)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    track: Mapped["Track"] = relationship(back_populates="analyses")


class TrackVideo(Base):
    """Music video downloads linked to tracks (Phase 5)."""

    __tablename__ = "track_videos"
    __table_args__ = (
        UniqueConstraint("track_id", "source", "source_id", name="uq_track_video"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    track_id: Mapped[UUID] = mapped_column(ForeignKey("tracks.id", ondelete="CASCADE"))

    source: Mapped[str] = mapped_column(String(50), nullable=False)  # 'youtube', 'vimeo', etc.
    source_id: Mapped[str] = mapped_column(String(100), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(500))

    # Local storage
    file_path: Mapped[str | None] = mapped_column(String(1000))
    is_audio_only: Mapped[bool] = mapped_column(Boolean, default=False)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger)

    # Metadata from source
    video_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # User interaction
    match_confirmed_by: Mapped[UUID | None] = mapped_column()  # Profile ID who confirmed the match
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_played_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Relationships
    track: Mapped["Track"] = relationship()
