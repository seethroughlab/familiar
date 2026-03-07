"""Drop new releases tables (artist_new_releases, artist_check_cache).

Revision ID: 20260306_drop_nr
Revises: 20260306_drop_subsonic
Create Date: 2026-03-06
"""

import sqlalchemy as sa
from alembic import op

revision = "20260306_drop_nr"
down_revision = "20260306_drop_subsonic"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = :table"
    ), {"table": table_name})
    return result.fetchone() is not None


def upgrade() -> None:
    if _table_exists("artist_new_releases"):
        op.drop_table("artist_new_releases")
    if _table_exists("artist_check_cache"):
        op.drop_table("artist_check_cache")


def downgrade() -> None:
    pass
