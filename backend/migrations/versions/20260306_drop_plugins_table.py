"""Drop plugins table (community plugins feature shelved).

Revision ID: 20260306_drop_plugins
Revises: 20260225_analysis_gaps
Create Date: 2026-03-06 00:00:00
"""

from collections.abc import Sequence

from alembic import op

from migrations.helpers import table_exists

# revision identifiers, used by Alembic.
revision: str = "20260306_drop_plugins"
down_revision: str | None = "20260225_analysis_gaps"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop plugins table."""
    if not table_exists("plugins"):
        return
    op.drop_table("plugins")


def downgrade() -> None:
    """No-op — plugins table is not recreated."""
    pass
