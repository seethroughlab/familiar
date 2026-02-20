"""Add functional indexes for lower(trim(...)) expressions on tracks.

These expressions are used ~22 times across library.py but had no matching
index, forcing full table scans on the 23K-track library.

Revision ID: 20260220_ltrim_idx
Revises: 20260220_fix_melodic
Create Date: 2026-02-20
"""

import sqlalchemy as sa
from alembic import op

revision = "20260220_ltrim_idx"
down_revision = "20260220_fix_melodic"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_tracks_artist_lower "
        "ON tracks (lower(trim(artist)))"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_tracks_album_lower "
        "ON tracks (lower(trim(album)))"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_tracks_album_artist_lower "
        "ON tracks (lower(trim(COALESCE(NULLIF(album_artist, ''), artist))))"
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_tracks_album_artist_lower"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_tracks_album_lower"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_tracks_artist_lower"))
