"""Pass 4: retire ``artist_info`` for ``external_artist_image_cache``.

After Passes 1-3, ``artist_info`` is legacy for library artists — Pass
1's backfill moved bio/image/similar onto ``Artist``, and Pass 2/3 cut
all read paths over to ``Artist``. The only remaining role of the
legacy table is as a name-keyed image cache used by
``services/artist_image.py`` for the Wikipedia/Wikidata/Spotify
resolver chain (including non-library similar-artist suggestions).

Pass 4 replaces it with a thinner table holding only the four columns
the resolver actually needs: ``(name_normalized PK, artist_name,
image_url, image_checked_at)``. Cache rows are copied across in the
same migration so we don't lose positive hits or negative-cache
markers, then the legacy table is dropped.

Revision ID: 20260428_external_artist_img
Revises: 20260428_canonical_album_artist
Create Date: 2026-04-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import table_exists

revision: str = "20260428_external_artist_img"
down_revision: str | None = "20260428_canonical_album_artist"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not table_exists("external_artist_image_cache"):
        op.create_table(
            "external_artist_image_cache",
            sa.Column("name_normalized", sa.Text(), primary_key=True),
            sa.Column("artist_name", sa.Text(), nullable=False),
            sa.Column("image_url", sa.Text(), nullable=True),
            sa.Column("image_checked_at", sa.DateTime(), nullable=True),
        )

    # Data migration: copy every artist_info cache row that has a
    # checked_at timestamp (positive hits + negative-cache markers).
    # Library artists already have image_url on Artist via Pass 1's
    # backfill, so this preserves the non-library cache without
    # creating duplicates that would conflict with the new resolver
    # write path.
    if table_exists("artist_info"):
        op.execute(
            """
            INSERT INTO external_artist_image_cache (name_normalized, artist_name, image_url, image_checked_at)
            SELECT artist_name_normalized, artist_name, image_url, image_checked_at
            FROM artist_info
            WHERE image_checked_at IS NOT NULL
            ON CONFLICT (name_normalized) DO NOTHING
            """
        )
        op.drop_table("artist_info")


def downgrade() -> None:
    """No-op per repo migration policy."""
    pass
