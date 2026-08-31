from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Artist(Base):
    """Canonical artist row — one per real artist.

    Pass 1 of the canonical-artists migration: this table is populated by
    the backfill CLI and the scanner dual-write path, but read endpoints
    still group by ``Track.artist`` string. Pass 2 cuts over the reads.

    Aliases (every observed tag spelling for this artist) live in
    ``artist_aliases``; ``Track.canonical_artist_id`` points back here.
    """

    __tablename__ = "artists"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    sort_name: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    musicbrainz_id: Mapped[str | None] = mapped_column(String(36), unique=True)

    # Resolved photo (migrated from artist_info.image_url during backfill).
    image_url: Mapped[str | None] = mapped_column(Text)
    image_checked_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Last.fm-sourced fields, also migrated from artist_info during backfill.
    bio_summary: Mapped[str | None] = mapped_column(Text)
    bio_content: Mapped[str | None] = mapped_column(Text)
    lastfm_url: Mapped[str | None] = mapped_column(String(500))
    listeners: Mapped[int | None] = mapped_column(Integer)
    playcount: Mapped[int | None] = mapped_column(BigInteger)
    similar_artists: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    tags: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime)
    fetch_error: Mapped[str | None] = mapped_column(String(500))

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class ArtistAlias(Base):
    """Maps an observed artist tag spelling to its canonical ``Artist``.

    The primary key is the normalized alias (``normalize_artist_name``)
    so the resolver can do a one-shot ``db.get(ArtistAlias, normalized)``
    to find the canonical row for any tag string.
    """

    __tablename__ = "artist_aliases"

    alias_normalized: Mapped[str] = mapped_column(Text, primary_key=True)
    alias: Mapped[str] = mapped_column(Text, nullable=False)
    artist_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("artists.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Provenance: 'tag' (auto from scan/backfill), 'mb' (added because MB
    # listed it as an alias), 'manual_merge' (admin merge UI added it).
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class ExternalArtistImageCache(Base):
    """Cache of resolved artist images for any queried artist name.

    Used by ``services/artist_image.py`` as a name-keyed cache for the
    Wikipedia → Wikidata → Spotify resolver chain. For library artists,
    ``Artist.image_url`` is the authoritative read source — the
    resolver also writes through to that column when an alias for the
    name exists. This table is the fallback for non-library artists
    (similar-artist photos in detail panels) and the negative cache
    (``image_checked_at`` set, ``image_url`` NULL, refresh after TTL).

    Replaced ``ArtistInfo`` in Pass 4. The legacy table held bio /
    listeners / similar / tags columns that Pass 1 migrated onto
    ``Artist`` and Pass 2/3 cut all read paths to source from there.
    """

    __tablename__ = "external_artist_image_cache"

    name_normalized: Mapped[str] = mapped_column(Text, primary_key=True)
    artist_name: Mapped[str] = mapped_column(Text, nullable=False)
    image_url: Mapped[str | None] = mapped_column(Text)
    image_checked_at: Mapped[datetime | None] = mapped_column(DateTime)


class ArtistCheckCache(Base):
    """Tracks when each library artist was last checked for new releases.

    Scoped to the new-releases background task (#3 surface). Holds polling
    cadence + priority, not album records.
    """

    __tablename__ = "artist_check_cache"

    artist_name_normalized: Mapped[str] = mapped_column(String(500), primary_key=True)
    musicbrainz_artist_id: Mapped[str | None] = mapped_column(String(36))
    last_checked_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # No `check_priority` column: the score is profile-relative and this table is
    # keyed per artist for the whole installation, so a stored value would be one
    # listener's opinion imposed on everyone. Recomputed per run in
    # `get_prioritized_artists_batch`. Dropped 2026-08-31, see ADR-0101.


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
            postgresql_where=text("discovery_context = 'artist_new_release'"),
        ),
        Index(
            "ix_eac_playlist_rec_unique",
            "release_id",
            "source_playlist_id",
            unique=True,
            postgresql_where=text("discovery_context = 'playlist_recommendation'"),
        ),
        Index(
            "ix_eac_listening_profile_unique",
            "release_id",
            unique=True,
            postgresql_where=text(
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
