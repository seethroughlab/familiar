"""Create `track_videos`, which the model has declared and no migration has ever built.

`TrackVideo` (`app/db/models/tracks.py`) has been declared and exported since Phase 5, and no
migration file in this directory mentions it. Fresh databases have the table only because the
baseline runs `Base.metadata.create_all()` — so **a database stamped at baseline before the model
landed does not have it**, and nothing reports that: `tests/test_migrations.py` records that the
baseline check "cannot detect schema drift, and used to claim it could", and the incremental check
only compares post-baseline DDL.

ADR-0086 starts writing rows here, so the table has to be guaranteed rather than assumed. Guarded
with `table_exists`, so this is a no-op on every database that already got it from `create_all`.

Revision ID: 20260825_track_videos
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import table_exists

revision: str = "20260825_track_videos"
down_revision: str | None = "20260812_canonical_albums"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if table_exists("track_videos"):
        return

    op.create_table(
        "track_videos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "track_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tracks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("source_id", sa.String(100), nullable=False),
        sa.Column("source_url", sa.String(500), nullable=True),
        sa.Column("file_path", sa.String(1000), nullable=True),
        sa.Column("is_audio_only", sa.Boolean(), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("video_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("match_confirmed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("downloaded_at", sa.DateTime(), nullable=True),
        sa.Column("last_played_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("track_id", "source", "source_id", name="uq_track_video"),
    )


def downgrade() -> None:
    # One-way: dropping this table would discard which video is attached to which track, and the
    # files on disk carry no record of it — `{track_id}.mp4` says nothing about its source.
    pass
