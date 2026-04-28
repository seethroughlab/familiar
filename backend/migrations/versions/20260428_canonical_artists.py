"""Canonical artists data model: artists, artist_aliases, tracks.canonical_artist_id.

Replaces the ad-hoc ``GROUP BY lower(trim(tracks.artist))`` pattern with a
real artist entity. ``artists`` holds canonical rows (one per real artist),
``artist_aliases`` maps every observed tag spelling to a canonical row, and
``tracks.canonical_artist_id`` is set at scan time and during backfill.

Pass 1 only adds the schema; read endpoints still group by string. Pass 2
will cut over the artist tile grid and the top-played consumers.

Revision ID: 20260428_canonical_artists
Revises: 20260427_artist_img
Create Date: 2026-04-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from migrations.helpers import column_exists, index_exists, table_exists

revision: str = "20260428_canonical_artists"
down_revision: str | None = "20260427_artist_img"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not table_exists("artists"):
        op.create_table(
            "artists",
            sa.Column(
                "id",
                PGUUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("sort_name", sa.Text(), nullable=False),
            sa.Column("musicbrainz_id", sa.String(36), nullable=True, unique=True),
            sa.Column("image_url", sa.Text(), nullable=True),
            sa.Column("image_checked_at", sa.DateTime(), nullable=True),
            sa.Column("bio_summary", sa.Text(), nullable=True),
            sa.Column("bio_content", sa.Text(), nullable=True),
            sa.Column("lastfm_url", sa.String(500), nullable=True),
            sa.Column("listeners", sa.Integer(), nullable=True),
            sa.Column("playcount", sa.BigInteger(), nullable=True),
            sa.Column(
                "similar_artists",
                JSONB(),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column(
                "tags",
                JSONB(),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column("fetched_at", sa.DateTime(), nullable=True),
            sa.Column("fetch_error", sa.String(500), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    if not index_exists("ix_artists_sort_name"):
        op.create_index("ix_artists_sort_name", "artists", ["sort_name"])

    if not table_exists("artist_aliases"):
        op.create_table(
            "artist_aliases",
            sa.Column("alias_normalized", sa.Text(), primary_key=True),
            sa.Column("alias", sa.Text(), nullable=False),
            sa.Column(
                "artist_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("artists.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("source", sa.String(20), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    if not index_exists("ix_artist_aliases_artist_id"):
        op.create_index(
            "ix_artist_aliases_artist_id", "artist_aliases", ["artist_id"]
        )

    if not column_exists("tracks", "canonical_artist_id"):
        op.add_column(
            "tracks",
            sa.Column(
                "canonical_artist_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("artists.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )

    if not index_exists("ix_tracks_canonical_artist_id"):
        op.create_index(
            "ix_tracks_canonical_artist_id", "tracks", ["canonical_artist_id"]
        )


def downgrade() -> None:
    """No-op per repo migration policy."""
    pass
