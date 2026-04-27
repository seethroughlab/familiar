"""Recreate artist_check_cache and add generic external_album_cache.

Revival of the new-releases feature, now backed by a generic external album
cache table that can also serve playlist-context external recommendations
(distinguished by the ``discovery_context`` column).

Revision ID: 20260426_ext_albums
Revises: 20260319_pend_review
Create Date: 2026-04-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import index_exists, table_exists

revision: str = "20260426_ext_albums"
down_revision: str | None = "20260319_pend_review"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not table_exists("artist_check_cache"):
        op.create_table(
            "artist_check_cache",
            sa.Column("artist_name_normalized", sa.String(length=500), primary_key=True),
            sa.Column("musicbrainz_artist_id", sa.String(length=36), nullable=True),
            sa.Column(
                "last_checked_at",
                sa.DateTime(),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("check_priority", sa.Float(), nullable=False, server_default="0"),
            sa.Column("priority_updated_at", sa.DateTime(), nullable=True),
        )

    if not table_exists("external_album_cache"):
        op.create_table(
            "external_album_cache",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("release_id", sa.String(length=100), nullable=False),
            sa.Column("discovery_context", sa.String(length=40), nullable=False),
            sa.Column("artist_name", sa.String(length=500), nullable=False),
            sa.Column("artist_name_normalized", sa.String(length=500), nullable=False),
            sa.Column("musicbrainz_artist_id", sa.String(length=36), nullable=True),
            sa.Column("release_name", sa.String(length=500), nullable=False),
            sa.Column("release_type", sa.String(length=20), nullable=True),
            sa.Column("release_date", sa.DateTime(), nullable=True),
            sa.Column("artwork_url", sa.String(length=500), nullable=True),
            sa.Column("external_url", sa.String(length=500), nullable=True),
            sa.Column("track_count", sa.Integer(), nullable=True),
            sa.Column(
                "extra_data",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("dismissed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column(
                "dismissed_by_profile_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("profiles.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "local_album_match",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column(
                "discovered_at",
                sa.DateTime(),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )

    if not index_exists("ix_external_album_cache_release_id"):
        op.create_index(
            "ix_external_album_cache_release_id",
            "external_album_cache",
            ["release_id"],
            unique=True,
        )
    if not index_exists("ix_external_album_cache_artist_name_normalized"):
        op.create_index(
            "ix_external_album_cache_artist_name_normalized",
            "external_album_cache",
            ["artist_name_normalized"],
        )
    if not index_exists("ix_external_album_cache_dismissed"):
        op.create_index(
            "ix_external_album_cache_dismissed",
            "external_album_cache",
            ["dismissed"],
        )
    if not index_exists("ix_external_album_cache_local_album_match"):
        op.create_index(
            "ix_external_album_cache_local_album_match",
            "external_album_cache",
            ["local_album_match"],
        )
    if not index_exists("ix_external_album_cache_discovery_context"):
        op.create_index(
            "ix_external_album_cache_discovery_context",
            "external_album_cache",
            ["discovery_context"],
        )


def downgrade() -> None:
    """No-op per repo migration policy."""
    pass
