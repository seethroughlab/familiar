"""Drop subsonic_credentials table.

Revision ID: 20260306_drop_subsonic
Revises: 20260306_drop_plugins
Create Date: 2026-03-06 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260306_drop_subsonic"
down_revision: str | None = "20260306_drop_plugins"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(table_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_name = :table)"
        ),
        {"table": table_name},
    )
    return bool(result.scalar())


def upgrade() -> None:
    """Drop subsonic_credentials table."""
    if _table_exists("subsonic_credentials"):
        op.drop_table("subsonic_credentials")


def downgrade() -> None:
    """No-op: subsonic API has been removed."""
    pass
