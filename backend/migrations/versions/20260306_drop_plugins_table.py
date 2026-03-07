"""Drop plugins table (community plugins feature shelved).

Revision ID: 20260306_drop_plugins
Revises: 20260225_analysis_gaps
Create Date: 2026-03-06 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260306_drop_plugins"
down_revision: str | None = "20260225_analysis_gaps"
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
    """Drop plugins table."""
    if not _table_exists("plugins"):
        return
    op.drop_table("plugins")


def downgrade() -> None:
    """No-op — plugins table is not recreated."""
    pass
