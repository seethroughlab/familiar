"""Add mixtapes table for the Mix Tape Export feature.

A mixtape is a single rendered MP3 produced by editing 2–15 tracks from
a static or smart playlist together (with optional crossfade), plus a
generated cover image and tracklist .txt bundled into one ZIP.

Revision ID: 20260429_add_mixtapes
Revises: 20260428_external_artist_img
Create Date: 2026-04-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import index_exists, table_exists

revision: str = "20260429_add_mixtapes"
down_revision: str | None = "20260428_external_artist_img"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not table_exists("mixtapes"):
        op.create_table(
            "mixtapes",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "profile_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("profiles.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(length=64), nullable=False),
            sa.Column(
                "source_playlist_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("playlists.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "source_smart_playlist_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("smart_playlists.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "track_ids",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column("crossfade_seconds", sa.Integer(), nullable=True),
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'pending'"),
            ),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("audio_path", sa.String(length=1000), nullable=True),
            sa.Column("cover_path", sa.String(length=1000), nullable=True),
            sa.Column("tracklist_path", sa.String(length=1000), nullable=True),
            sa.Column("bundle_path", sa.String(length=1000), nullable=True),
            sa.Column("duration_seconds", sa.Float(), nullable=True),
            sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
        )

    if not index_exists("ix_mixtapes_profile_id"):
        op.create_index("ix_mixtapes_profile_id", "mixtapes", ["profile_id"])
    if not index_exists("ix_mixtapes_status"):
        op.create_index("ix_mixtapes_status", "mixtapes", ["status"])


def downgrade() -> None:
    """No-op per repo migration policy."""
    pass
