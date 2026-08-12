"""Canonical albums data model: albums, album_aliases, tracks.canonical_album_id.

ADR-0052. The mirror of ``20260428_canonical_artists`` — an album stops being whatever
a ``GROUP BY`` over tag strings says it is and becomes a row with a surrogate id.

The id is what artwork gets filed under, so renaming an album changes the row's
matching inputs while its identity stays put and the cover follows it. The hash it
replaces (``compute_album_hash``) was derived from the tags themselves, so correcting a
spelling silently re-keyed the artwork to a slot nothing had ever fetched.

Schema only. Read endpoints still group by string; the backfill CLI and the scanner
dual-write populate the columns, exactly as Pass 1 did for artists.

Revision ID: 20260812_canonical_albums
Revises: 20260811_metadata_overrides
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from migrations.helpers import column_exists, index_exists, table_exists

revision: str = "20260812_canonical_albums"
down_revision: str | None = "20260811_metadata_overrides"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not table_exists("albums"):
        op.create_table(
            "albums",
            sa.Column(
                "id",
                PGUUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("sort_name", sa.Text(), nullable=False),
            # SET NULL, not CASCADE: losing an artist row must not delete the record.
            sa.Column(
                "album_artist_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("artists.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("musicbrainz_release_id", sa.String(36), nullable=True, unique=True),
            sa.Column("year", sa.Integer(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )

    if not index_exists("albums", "ix_albums_sort_name"):
        op.create_index("ix_albums_sort_name", "albums", ["sort_name"])
    if not index_exists("albums", "ix_albums_album_artist_id"):
        op.create_index("ix_albums_album_artist_id", "albums", ["album_artist_id"])

    if not table_exists("album_aliases"):
        op.create_table(
            "album_aliases",
            # The normalized key is the PK so the resolver can do a single
            # `db.get(AlbumAlias, key)`. Two shapes, both opaque outside the resolver:
            # "{album_artist_id}::{normalized title}", or "folder::{directory}" for
            # tracks with no album tag.
            sa.Column("alias_normalized", sa.Text(), primary_key=True),
            sa.Column("alias", sa.Text(), nullable=False),
            sa.Column(
                "album_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("albums.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("source", sa.String(20), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )

    if not index_exists("album_aliases", "ix_album_aliases_album_id"):
        op.create_index("ix_album_aliases_album_id", "album_aliases", ["album_id"])

    if not column_exists("tracks", "canonical_album_id"):
        op.add_column(
            "tracks",
            sa.Column(
                "canonical_album_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("albums.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    if not index_exists("tracks", "ix_tracks_canonical_album_id"):
        op.create_index("ix_tracks_canonical_album_id", "tracks", ["canonical_album_id"])


def downgrade() -> None:
    # No-op per repo migration policy: migrations are one-way and the guards above
    # make `alembic upgrade head` safe to re-run after a partial failure.
    pass
