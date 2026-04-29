"""Add mixtapes.byline column for the curator credit on mixtapes.

Renders as "by <byline>" on the cover image, and is written into the
audio file's TPE2 (album artist) and TPE4 (interpreter/compiler) ID3
frames so a recipient sees who made the mixtape in their music player.

Revision ID: 20260429_mixtapes_byline
Revises: 20260429_add_mixtapes
Create Date: 2026-04-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import column_exists

revision: str = "20260429_mixtapes_byline"
down_revision: str | None = "20260429_add_mixtapes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not column_exists("mixtapes", "byline"):
        op.add_column("mixtapes", sa.Column("byline", sa.String(length=32), nullable=True))


def downgrade() -> None:
    """No-op per repo migration policy."""
    pass
