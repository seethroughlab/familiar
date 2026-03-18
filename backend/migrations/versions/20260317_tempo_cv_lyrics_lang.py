"""Add tempo_cv to track_analysis and lyrics_language to tracks.

tempo_cv: promotes existing JSONB value to typed column for LLM filtering.
lyrics_language: ISO 639-1 language code detected from embedded lyrics.

Revision ID: 20260317_tempo_cv_lang
Revises: 20260313_norm_unicode_ws
Create Date: 2026-03-17
"""

import sqlalchemy as sa
from alembic import op

from migrations.helpers import column_exists

revision = "20260317_tempo_cv_lang"
down_revision = "20260313_norm_unicode_ws"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. tempo_cv on track_analysis (promote from JSONB)
    if not column_exists("track_analysis", "tempo_cv"):
        op.add_column(
            "track_analysis",
            sa.Column("tempo_cv", sa.Float, nullable=True),
        )

    # 2. lyrics_language on tracks
    if not column_exists("tracks", "lyrics_language"):
        op.add_column(
            "tracks",
            sa.Column("lyrics_language", sa.String(10), nullable=True),
        )

    conn = op.get_bind()

    # Backfill tempo_cv from existing analysis_detail JSONB
    conn.execute(
        sa.text(
            "UPDATE track_analysis SET tempo_cv = (analysis_detail->'rhythmic'->>'tempo_cv')::float "
            "WHERE analysis_detail->'rhythmic'->>'tempo_cv' IS NOT NULL AND tempo_cv IS NULL"
        )
    )

    # Backfill lyrics_language from existing lyrics
    rows = conn.execute(
        sa.text("SELECT id, lyrics FROM tracks WHERE lyrics IS NOT NULL AND lyrics != '' AND lyrics_language IS NULL")
    ).fetchall()
    if rows:
        from app.services.metadata.reader import detect_lyrics_language
        for row in rows:
            lang = detect_lyrics_language(row.lyrics)
            if lang:
                conn.execute(
                    sa.text("UPDATE tracks SET lyrics_language = :lang WHERE id = :id"),
                    {"lang": lang, "id": row.id},
                )


def downgrade() -> None:
    if column_exists("tracks", "lyrics_language"):
        op.drop_column("tracks", "lyrics_language")
    if column_exists("track_analysis", "tempo_cv"):
        op.drop_column("track_analysis", "tempo_cv")
