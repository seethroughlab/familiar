"""add spotify_imports table

Revision ID: 20260309_spotify_imports
Revises: 20260307_drop_is_wishlist
Create Date: 2026-03-09

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.helpers import table_exists

revision: str = "20260309_spotify_imports"
down_revision: str | None = "20260307_drop_is_wishlist"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not table_exists("spotify_imports"):
        op.create_table(
            "spotify_imports",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("profile_id", sa.Uuid(), sa.ForeignKey("profiles.id", ondelete="CASCADE"), unique=True, nullable=False),
            sa.Column("imported_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("spotify_username", sa.String(255), nullable=True),
            sa.Column("favorites", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("playlists", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("streaming_stats", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("match_results", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("summary", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        )


def downgrade() -> None:
    if table_exists("spotify_imports"):
        op.drop_table("spotify_imports")
