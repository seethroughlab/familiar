from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Album(Base):
    """Canonical album row — one per real record (ADR-0052).

    The mirror of ``Artist``, and built for the same reason: an album used to be
    whatever a ``GROUP BY`` over tag strings said it was, computed fresh on every
    request, with six definitions across the backend that disagreed at the edges.

    **The id is the point.** Artwork is filed under it, so renaming an album changes
    this row's matching inputs while its identity stays put and the cover follows.
    A key derived from the tags themselves — which is what
    ``compute_album_hash`` was — moves the moment somebody corrects a spelling, and
    ADR-0051's metadata editor makes correcting spellings a thing people do.

    Populated by the backfill CLI and the scanner dual-write. Read endpoints still
    group by tag strings; the read cutover is a follow-up, exactly as it was for
    artists (``docs/CANONICAL-ARTISTS.md``).
    """

    __tablename__ = "albums"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    sort_name: Mapped[str] = mapped_column(Text, nullable=False, index=True)

    # The album's artist, as a canonical id rather than a string. This is what makes
    # album identity inherit artist identity: merging two artists in the cleanup UI
    # merges their albums for free, and "Beatles / Revolver" and "The Beatles /
    # Revolver" are one album without anybody saying so.
    #
    # SET NULL rather than CASCADE — losing an artist row must not delete the record.
    album_artist_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("artists.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Authoritative where present and absent almost everywhere: 1,782 of 26,422
    # tracks carried one when this was measured. First step of the resolver's
    # cascade, never identity on its own.
    musicbrainz_release_id: Mapped[str | None] = mapped_column(String(36), unique=True)

    year: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AlbumAlias(Base):
    """Maps an observed album spelling to its canonical ``Album``.

    The normalized alias is the **primary key**, copying ``ArtistAlias``, so the
    resolver finds an album with a single ``db.get(AlbumAlias, key)`` — a PK fetch
    that the session's identity map caches, with no query planning.

    Two key shapes, both opaque to everything but the resolver:

    - ``"{album_artist_id}::{normalize_for_matching(title)}"`` — the ordinary case.
      The artist half is a **uuid, not a string**, which is what makes album identity
      inherit artist identity.
    - ``"folder::{directory}"`` — for the 801 tracks that have no album tag at all.
      They used to share one ``unknown::unknown`` artwork bucket, so a single dropped
      cover would land on 61 unrelated tracks. 97.5% of directories in this library
      hold exactly one album, which makes the folder the best guess available when
      there is nothing else to go on.
    """

    __tablename__ = "album_aliases"

    alias_normalized: Mapped[str] = mapped_column(Text, primary_key=True)
    # The raw title as tagged, kept for forensics — the normalized key is lossy.
    alias: Mapped[str] = mapped_column(Text, nullable=False)
    album_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("albums.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Provenance: 'tag' (scan or backfill), 'mb' (MusicBrainz listed it),
    # 'folder' (no album tag, keyed by directory), 'manual_merge' (a future merge UI).
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
