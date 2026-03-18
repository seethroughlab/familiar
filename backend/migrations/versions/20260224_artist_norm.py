"""Drop artist_normalized and featuring_artists columns from tracks.

Reverts the automated feat.-stripping columns. Compilation detection
now uses regexp_replace in SQL instead of persisted columns.
Album grouping uses the existing album_artist field set via bulk edit.

Revision ID: 20260224_drop_artnorm
Revises: 20260220_ltrim_idx
Create Date: 2026-02-24
"""

import sqlalchemy as sa
from alembic import op

from migrations.helpers import column_exists

revision = "20260224_drop_artnorm"
down_revision = "20260220_ltrim_idx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_tracks_artist_norm_lower"))

    if column_exists("tracks", "artist_normalized"):
        op.execute(sa.text("DROP INDEX IF EXISTS ix_tracks_artist_normalized"))
        op.drop_column("tracks", "artist_normalized")

    if column_exists("tracks", "featuring_artists"):
        op.drop_column("tracks", "featuring_artists")


def downgrade() -> None:
    if not column_exists("tracks", "artist_normalized"):
        op.add_column("tracks", sa.Column("artist_normalized", sa.String(500)))
        op.create_index("ix_tracks_artist_normalized", "tracks", ["artist_normalized"])

    if not column_exists("tracks", "featuring_artists"):
        op.add_column("tracks", sa.Column("featuring_artists", sa.String(500)))
