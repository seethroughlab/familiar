"""Add profile_external_favorites table.

Allows users to favorite external tracks (Spotify imports, LLM recommendations)
that aren't in the local library.

Revision ID: 20260213_ext_favorites
Revises: 20260211_drop_ext_preview
Create Date: 2026-02-13
"""

import sqlalchemy as sa
from alembic import op

revision = "20260213_ext_favorites"
down_revision = "20260211_drop_ext_preview"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name = :table"
        ),
        {"table": table_name},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    # external_tracks no longer exists (shelved feature) — skip on fresh DBs
    if not _table_exists("external_tracks"):
        return
    if not _table_exists("profile_external_favorites"):
        op.create_table(
            "profile_external_favorites",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("profile_id", sa.Uuid(), nullable=False),
            sa.Column("external_track_id", sa.Uuid(), nullable=False),
            sa.Column(
                "favorited_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["profile_id"], ["profiles.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["external_track_id"], ["external_tracks.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "profile_id",
                "external_track_id",
                name="uq_profile_external_favorite",
            ),
        )
        op.create_index(
            "ix_profile_external_favorites_profile_id",
            "profile_external_favorites",
            ["profile_id"],
        )
        op.create_index(
            "ix_profile_external_favorites_external_track_id",
            "profile_external_favorites",
            ["external_track_id"],
        )


def downgrade() -> None:
    if _table_exists("profile_external_favorites"):
        op.drop_table("profile_external_favorites")
