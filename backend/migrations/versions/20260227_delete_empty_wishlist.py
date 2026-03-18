"""Delete external tracks with empty/whitespace-only titles from wishlist.

These were created via POST /playlists/wishlist/add before title validation
was added. PlaylistTrack entries cascade-delete automatically.

Revision ID: 20260227_empty_wishlist
Revises: 20260225_analysis_gaps
Create Date: 2026-02-27
"""

import sqlalchemy as sa
from alembic import op

from migrations.helpers import table_exists

revision = "20260227_empty_wishlist"
down_revision = "20260225_analysis_gaps"


def upgrade() -> None:
    if table_exists("external_tracks"):
        op.execute(sa.text(
            "DELETE FROM external_tracks "
            "WHERE source = 'manual' AND trim(title) = ''"
        ))


def downgrade() -> None:
    # One-way: data cleanup
    pass
