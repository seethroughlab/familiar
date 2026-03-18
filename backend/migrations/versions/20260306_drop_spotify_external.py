"""Drop Spotify and external tracks tables/columns.

Revision ID: 20260306_drop_spt_ext
Revises: 20260306_drop_nr
Create Date: 2026-03-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import column_exists, constraint_exists, index_exists, table_exists

revision: str = "20260306_drop_spt_ext"
down_revision: str | None = "20260306_drop_nr"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Delete orphaned playlist_tracks rows where track_id IS NULL (external-only entries)
    op.execute(sa.text(
        "DELETE FROM playlist_tracks WHERE track_id IS NULL"
    ))

    # 2. Drop index on playlist_tracks.external_track_id
    if index_exists("ix_playlist_tracks_external"):
        op.drop_index("ix_playlist_tracks_external", table_name="playlist_tracks")

    # 3. Drop XOR CheckConstraint on playlist_tracks
    if constraint_exists("playlist_tracks", "ck_playlist_track_exactly_one_ref"):
        op.drop_constraint("ck_playlist_track_exactly_one_ref", "playlist_tracks", type_="check")

    # 4. Drop playlist_tracks.external_track_id column
    if column_exists("playlist_tracks", "external_track_id"):
        op.drop_column("playlist_tracks", "external_track_id")

    # 4b. Make track_id NOT NULL (all external-only rows already deleted in step 1)
    op.alter_column("playlist_tracks", "track_id", nullable=False, existing_type=sa.Uuid())

    # 5. Drop profile_external_favorites table
    if table_exists("profile_external_favorites"):
        op.drop_table("profile_external_favorites")

    # 6. Drop spotify_favorites table
    if table_exists("spotify_favorites"):
        op.drop_table("spotify_favorites")

    # 7. Drop spotify_profiles table
    if table_exists("spotify_profiles"):
        op.drop_table("spotify_profiles")

    # 8. Drop external_tracks table
    if table_exists("external_tracks"):
        op.drop_table("external_tracks")


def downgrade() -> None:
    # One-way: columns and tables removed from codebase
    pass
