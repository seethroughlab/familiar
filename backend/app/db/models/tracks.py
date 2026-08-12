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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import AlbumType, Base, TrackStatus


class Track(Base):
    """Core track entity with metadata from file tags."""

    __tablename__ = "tracks"

    # These are declared here rather than left to the migrations that first created them, because
    # the baseline builds fresh databases with `Base.metadata.create_all()` — so anything the models
    # do not describe is schema only an incremental migration can produce. `scripts/diff_schema.py`
    # found all seven of these present in every migrated database and in no model.
    #
    # The functional ones are `text()` rather than `func.lower(...)`: Postgres normalises both to the
    # same `indexdef`, and the literal form is what the migrations wrote and what the reflected
    # definition reads back as, so a future diff compares like with like.
    __table_args__ = (
        # Trigram indexes behind library search — without them `%` and ILIKE scan the table.
        Index("ix_tracks_title_trgm", "title",
              postgresql_using="gin", postgresql_ops={"title": "gin_trgm_ops"}),
        Index("ix_tracks_artist_trgm", "artist",
              postgresql_using="gin", postgresql_ops={"artist": "gin_trgm_ops"}),
        Index("ix_tracks_album_trgm", "album",
              postgresql_using="gin", postgresql_ops={"album": "gin_trgm_ops"}),
        # Case- and whitespace-insensitive lookup. The grouping queries sort and join on exactly
        # these expressions, so a plain column index does not serve them.
        Index("ix_tracks_artist_lower", text("lower(trim(artist))")),
        Index("ix_tracks_album_lower", text("lower(trim(album))")),
        Index("ix_tracks_album_artist_lower",
              text("lower(trim(coalesce(nullif(album_artist, ''), artist)))")),
        # Partial: the pending-review queue is a small slice of a large table.
        Index("ix_tracks_pending_review", "created_at",
              postgresql_where=text("status = 'pending_review'")),
    )

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
    codec: Mapped[str | None] = mapped_column(String(50))  # e.g. "aac", "alac", "flac", "mp3"
    needs_transcode: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    # External IDs (from MusicBrainz, etc.)
    musicbrainz_track_id: Mapped[str | None] = mapped_column(String(36))
    musicbrainz_artist_id: Mapped[str | None] = mapped_column(String(36))
    musicbrainz_album_id: Mapped[str | None] = mapped_column(String(36))
    isrc: Mapped[str | None] = mapped_column(String(12))

    # Canonical artist FK — populated by scanner dual-write and backfill.
    canonical_artist_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("artists.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Canonical album_artist FK — separate from canonical_artist_id so a
    # track tagged ``artist="John Lennon" album_artist="The Beatles"``
    # surfaces under both. Populated by the same scanner+backfill paths.
    canonical_album_artist_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("artists.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

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
    lyrics_language: Mapped[str | None] = mapped_column(String(10))  # ISO 639-1

    # Cached synced lyrics fetched from LRCLIB (for the lyrics visualizer).
    # Shape: {"synced": bool, "lines": [{"time": float, "text": str}],
    #         "plain_text": str, "source": str}
    synced_lyrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # User overrides for auto-detected analysis values
    # Example: {"bpm": 124.0, "key": "Am"} - overrides analysis.features values
    user_overrides: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    # Tag fields a person corrected in Familiar, and what they set them to.
    # Example: {"album": "Selenography", "year": None}
    #
    # These win over the file. `LibraryScanner._update_track` re-reads a file's tags when its hash
    # changes and would otherwise overwrite a deliberate correction with whatever the file says —
    # which is how a re-tag or a re-encode elsewhere silently undid work done here.
    #
    # Separate from `user_overrides` on purpose: that one overrides *analysis* values and is merged
    # only where the key already exists in the feature set. This one answers a different question,
    # namely who wins between the library and the file, and the answer is recorded per field so an
    # untouched field still follows the file.
    #
    # A null value is a real entry meaning "the person cleared this", not an absent one.
    metadata_overrides: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    # Analysis status
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

    # Review queue metadata (populated when status=PENDING_REVIEW, null otherwise)
    review_info: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Relationships
    analyses: Mapped[list["TrackAnalysis"]] = relationship(
        back_populates="track", cascade="all, delete"
    )
    playlist_entries: Mapped[list["PlaylistTrack"]] = relationship(
        back_populates="track", cascade="all, delete"
    )

    @classmethod
    def active_filter(cls):
        """Standard filter to exclude non-active tracks from queries."""
        return cls.status == TrackStatus.ACTIVE

    @property
    def analysis_version(self) -> int:
        """Derived from TrackAnalysis for API backward compatibility."""
        from sqlalchemy import inspect as sa_inspect

        if "analyses" in sa_inspect(self).unloaded:
            return 0
        return self.analyses[0].features_version if self.analyses else 0



# All scalar feature columns on TrackAnalysis
ANALYSIS_FEATURE_COLUMNS = [
    # From librosa (Phase 1)
    "bpm", "key", "energy", "danceability", "valence", "acousticness",
    "instrumentalness", "speechiness", "loudness_lufs", "track_peak",
    "replaygain_track_gain",
    # From analysis algorithms (Phase 1)
    "harmonic_complexity", "key_stability", "modal_character", "modal_confidence",
    "swing_ratio", "syncopation", "tempo_character", "tempo_cv", "brightness",
    "dynamic_range_db", "energy_shape", "section_count", "form_string",
    "avg_section_length",
    # Melodic (Phase 3)
    "note_density", "interval_character", "pitch_range",
]


class TrackAnalysis(Base):
    """Versioned audio analysis with typed feature columns and vector embedding."""

    __tablename__ = "track_analysis"
    __table_args__ = (
        UniqueConstraint("track_id", name="uq_track_analysis_track_id"),
        Index("ix_track_analysis_bpm", "bpm"),
        Index("ix_track_analysis_energy", "energy"),
        Index("ix_track_analysis_valence", "valence"),
        Index("ix_track_analysis_key", "key"),
        Index("ix_track_analysis_swing_ratio", "swing_ratio"),
        Index("ix_track_analysis_brightness", "brightness"),
        Index("ix_track_analysis_mood_tags", "mood_tags", postgresql_using="gin"),
        # The index pgvector similarity search depends on. Without it every `<=>` comparison is a
        # sequential scan over the whole table, which is radio, playlist generation and the music
        # map — the slowest possible failure, and a silent one.
        Index("ix_track_analysis_embedding_hnsw", "embedding",
              postgresql_using="hnsw",
              postgresql_ops={"embedding": "vector_cosine_ops"},
              postgresql_with={"m": 16, "ef_construction": 64}),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    track_id: Mapped[UUID] = mapped_column(ForeignKey("tracks.id", ondelete="CASCADE"), index=True)
    features_version: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    embedding_version: Mapped[int] = mapped_column(Integer, default=0)

    # ── Typed feature columns (promoted from JSONB) ──────────────────────
    # Phase 1: librosa features
    bpm: Mapped[float | None] = mapped_column(Float)
    key: Mapped[str | None] = mapped_column(String(10))
    energy: Mapped[float | None] = mapped_column(Float)
    danceability: Mapped[float | None] = mapped_column(Float)
    valence: Mapped[float | None] = mapped_column(Float)
    acousticness: Mapped[float | None] = mapped_column(Float)
    instrumentalness: Mapped[float | None] = mapped_column(Float)
    speechiness: Mapped[float | None] = mapped_column(Float)
    loudness_lufs: Mapped[float | None] = mapped_column(Float)
    track_peak: Mapped[float | None] = mapped_column(Float)
    replaygain_track_gain: Mapped[float | None] = mapped_column(Float)

    # Phase 1: analysis algorithm scalars
    harmonic_complexity: Mapped[float | None] = mapped_column(Float)
    key_stability: Mapped[str | None] = mapped_column(String(20))
    modal_character: Mapped[str | None] = mapped_column(String(40))
    modal_confidence: Mapped[float | None] = mapped_column(Float)
    swing_ratio: Mapped[float | None] = mapped_column(Float)
    syncopation: Mapped[float | None] = mapped_column(Float)
    tempo_character: Mapped[str | None] = mapped_column(String(20))
    tempo_cv: Mapped[float | None] = mapped_column(Float)
    brightness: Mapped[float | None] = mapped_column(Float)
    dynamic_range_db: Mapped[float | None] = mapped_column(Float)
    energy_shape: Mapped[str | None] = mapped_column(String(20))
    section_count: Mapped[int | None] = mapped_column(Integer)
    form_string: Mapped[str | None] = mapped_column(String(50))
    avg_section_length: Mapped[float | None] = mapped_column(Float)

    # Phase 3: melodic features (NULL until Phase 3 runs)
    note_density: Mapped[float | None] = mapped_column(Float)
    interval_character: Mapped[str | None] = mapped_column(String(20))
    pitch_range: Mapped[int | None] = mapped_column(Integer)

    # ── Structural columns ───────────────────────────────────────────────
    # Full structured data for report generation (chord sequences, SSM image, etc.)
    analysis_detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    has_melodic: Mapped[bool] = mapped_column(Boolean, default=False)
    midi_path: Mapped[str | None] = mapped_column(String(500))
    melodic_version: Mapped[int] = mapped_column(Integer, default=0)

    # ── Confidence & cross-validation ──────────────────────────────────────
    # Per-feature confidence scores and cross-validation results
    feature_confidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Locally-computed features when external features are primary (for cross-validation)
    local_features: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # ── Mood/genre tags ──────────────────────────────────────────────────
    # CLAP-based mood, genre, instrumentation, and energy tags
    mood_tags: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    mood_tags_version: Mapped[int] = mapped_column(Integer, default=0)

    # ── Existing columns ─────────────────────────────────────────────────
    # Vector embedding for similarity search (CLAP produces 512-dim embeddings)
    embedding: Mapped[Any | None] = mapped_column(Vector(512))

    # Audio fingerprint for identification (base64-encoded, can be very long)
    acoustid: Mapped[str | None] = mapped_column(Text)

    # Cached AcoustID API lookup results (list of candidates with scores/recording IDs)
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

    def to_features_dict(self) -> dict[str, Any]:
        """Build a features dict from typed columns (preserves API shape)."""
        result: dict[str, Any] = {}
        for col in ANALYSIS_FEATURE_COLUMNS:
            val = getattr(self, col, None)
            if val is not None:
                result[col] = val
        return result


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
