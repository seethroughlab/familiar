"""Add image_url + image_checked_at to artist_info for resolved Wikipedia thumbnails.

Last.fm's similar-artist API returns a placeholder image URL for every artist
since ~2018. We resolve real artist photos via MusicBrainz url-rels →
Wikipedia REST summary → thumbnail.source, and cache the result here.

A NULL ``image_url`` with a recent ``image_checked_at`` is a negative cache
(artist has no Wikipedia page or no thumbnail). Re-resolved after 30 days.

Revision ID: 20260427_artist_img
Revises: 20260428_listening_prof
Create Date: 2026-04-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import column_exists, table_exists

revision: str = "20260427_artist_img"
down_revision: str | None = "20260428_listening_prof"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ``artist_info`` is dropped in the Pass 4 migration
    # (``20260428_external_artist_img``). When this migration runs
    # ahead of that one on a freshly-bootstrapped DB where
    # ``Base.metadata.create_all`` no longer creates ``artist_info``
    # (the model was removed in Pass 4), guard the ALTERs so this
    # migration is a no-op when the table is already absent.
    if not table_exists("artist_info"):
        return
    if not column_exists("artist_info", "image_url"):
        op.add_column("artist_info", sa.Column("image_url", sa.Text(), nullable=True))
    if not column_exists("artist_info", "image_checked_at"):
        op.add_column(
            "artist_info",
            sa.Column("image_checked_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    """No-op per repo migration policy."""
    pass
