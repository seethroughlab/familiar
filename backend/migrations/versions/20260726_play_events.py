"""Add play_events table for per-play listening feedback.

ProfilePlayHistory aggregates plays into a count plus a summed total_play_seconds,
which destroys per-play completion at write time — a track played once in full and one
skipped twenty times at three seconds are indistinguishable. This table records each
listening event intact so skips, completion ratios, and rejections stay recoverable.

ProfilePlayHistory is unchanged and keeps its existing semantics.

Revision ID: 20260726_play_events
Revises: 20260605_synced_lyrics
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import index_exists, table_exists

revision: str = "20260726_play_events"
down_revision: str | None = "20260605_synced_lyrics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not table_exists("play_events"):
        op.create_table(
            "play_events",
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
            sa.Column(
                "track_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("tracks.id", ondelete="CASCADE"),
                nullable=False,
            ),
            # The track this one was suggested from (radio insertion); NULL for ordinary plays
            sa.Column(
                "source_track_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("tracks.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "started_at",
                sa.DateTime(),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "played_seconds",
                sa.Float(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("track_duration", sa.Float(), nullable=True),
            sa.Column(
                "completion_ratio",
                sa.Float(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            # 'completed' | 'skipped' | 'rejected' | 'errored'
            sa.Column("outcome", sa.String(length=16), nullable=False),
            # 'library' | 'album' | 'playlist' | 'artist' | 'ephemeral' | 'radio' | 'ambient' | 'other'
            sa.Column("context", sa.String(length=16), nullable=True),
        )

    # Recent-history scans for a profile
    if not index_exists("ix_play_events_profile_started_at"):
        op.create_index(
            "ix_play_events_profile_started_at",
            "play_events",
            ["profile_id", "started_at"],
        )
    # Per-candidate feedback lookup when ranking (profile + track)
    if not index_exists("ix_play_events_profile_track"):
        op.create_index(
            "ix_play_events_profile_track",
            "play_events",
            ["profile_id", "track_id"],
        )
    # Supports the ON DELETE CASCADE from tracks
    if not index_exists("ix_play_events_track_id"):
        op.create_index("ix_play_events_track_id", "play_events", ["track_id"])


def downgrade() -> None:
    """No-op per repo migration policy."""
    pass
