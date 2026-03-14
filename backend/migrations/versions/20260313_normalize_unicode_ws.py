"""normalize unicode whitespace in track metadata

Revision ID: 20260313_norm_unicode_ws
Revises: 20260309_spotify_imports
Create Date: 2026-03-13

"""

import sqlalchemy as sa
from alembic import op

revision: str = "20260313_norm_unicode_ws"
down_revision: str | None = "20260309_spotify_imports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Fix mojibake: Â followed by NBSP (double-encoded UTF-8) -> regular space
    # Then replace remaining non-breaking spaces and other Unicode whitespace
    for col in ("title", "artist", "album", "album_artist", "genre", "composer"):
        # Step 1: Fix Â+NBSP mojibake
        conn.execute(sa.text(f"""
            UPDATE tracks
            SET {col} = replace({col}, E'\\u00C2\\u00A0', ' ')
            WHERE {col} LIKE E'%\\u00C2\\u00A0%'
        """))
        # Step 2: Replace NBSP and other Unicode whitespace with regular space
        conn.execute(sa.text(f"""
            UPDATE tracks
            SET {col} = regexp_replace({col}, E'[\\u00A0\\u2007\\u202F\\u2060]', ' ', 'g')
            WHERE {col} ~ E'[\\u00A0\\u2007\\u202F\\u2060]'
        """))
        # Step 3: Collapse multiple spaces and trim
        conn.execute(sa.text(f"""
            UPDATE tracks
            SET {col} = trim(regexp_replace({col}, '  +', ' ', 'g'))
            WHERE {col} LIKE '%  %'
        """))


def downgrade() -> None:
    # Data migration - no downgrade needed
    pass
