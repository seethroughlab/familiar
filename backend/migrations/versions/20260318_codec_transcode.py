"""Add codec and needs_transcode columns to tracks.

Stores the actual audio codec (from ffprobe) so we can detect files with
browser-unsupported codecs and transcode them on-the-fly at stream time.

Revision ID: 20260318_codec_xcode
Revises: 20260317_tempo_cv_lang
Create Date: 2026-03-18
"""

import sqlalchemy as sa
from alembic import op

from migrations.helpers import column_exists

revision = "20260318_codec_xcode"
down_revision = "20260317_search_perf_idx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not column_exists("tracks", "codec"):
        op.add_column(
            "tracks",
            sa.Column("codec", sa.String(50), nullable=True),
        )

    if not column_exists("tracks", "needs_transcode"):
        op.add_column(
            "tracks",
            sa.Column("needs_transcode", sa.Boolean, server_default="false", nullable=False),
        )

    # Backfill: 32-bit FLAC/WAV files need transcoding (browsers only support ≤24-bit)
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE tracks SET needs_transcode = true "
            "WHERE bit_depth IS NOT NULL AND bit_depth > 24 AND needs_transcode = false"
        )
    )


def downgrade() -> None:
    if column_exists("tracks", "needs_transcode"):
        op.drop_column("tracks", "needs_transcode")
    if column_exists("tracks", "codec"):
        op.drop_column("tracks", "codec")
