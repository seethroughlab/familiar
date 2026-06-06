"""Add synced_lyrics JSONB cache to tracks.

synced_lyrics: cached LRCLIB result for the lyrics visualizer so each track
switch doesn't re-hit the network. Shape:
{"synced": bool, "lines": [{"time": float, "text": str}],
 "plain_text": str, "source": str}

Revision ID: 20260605_synced_lyrics
Revises: 20260429_mixtapes_byline
Create Date: 2026-06-05
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.helpers import column_exists

revision = "20260605_synced_lyrics"
down_revision = "20260429_mixtapes_byline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not column_exists("tracks", "synced_lyrics"):
        op.add_column(
            "tracks",
            sa.Column("synced_lyrics", JSONB, nullable=True),
        )


def downgrade() -> None:
    if column_exists("tracks", "synced_lyrics"):
        op.drop_column("tracks", "synced_lyrics")
