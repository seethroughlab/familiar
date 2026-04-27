"""Per-playlist external-album recommendations.

Adds ``source_playlist_id`` to ``external_album_cache`` and replaces the
global UNIQUE on ``release_id`` with two partial unique indexes — one for
each ``discovery_context`` value, since the same release_id can legitimately
appear under different playlists for the playlist-recommendation context.

Revision ID: 20260427_ext_album_pl
Revises: 20260426_ext_albums
Create Date: 2026-04-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import column_exists, index_exists

revision: str = "20260427_ext_album_pl"
down_revision: str | None = "20260426_ext_albums"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not column_exists("external_album_cache", "source_playlist_id"):
        op.add_column(
            "external_album_cache",
            sa.Column(
                "source_playlist_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("playlists.id", ondelete="CASCADE"),
                nullable=True,
            ),
        )

    if not index_exists("ix_eac_source_playlist_context"):
        op.create_index(
            "ix_eac_source_playlist_context",
            "external_album_cache",
            ["source_playlist_id", "discovery_context"],
        )

    # Replace the global UNIQUE on release_id with two partial unique indexes.
    if index_exists("ix_external_album_cache_release_id"):
        op.drop_index("ix_external_album_cache_release_id")

    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_eac_artist_new_release_unique "
        "ON external_album_cache (release_id) "
        "WHERE discovery_context = 'artist_new_release'"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_eac_playlist_rec_unique "
        "ON external_album_cache (release_id, source_playlist_id) "
        "WHERE discovery_context = 'playlist_recommendation'"
    )


def downgrade() -> None:
    """No-op per repo migration policy."""
    pass
