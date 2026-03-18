"""Add subsonic_credentials table for Subsonic API auth.

Revision ID: 20260208_subsonic_creds
Revises: 20260208_autodownload_nn
Create Date: 2026-02-08 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import table_exists

# revision identifiers, used by Alembic.
revision: str = "20260208_subsonic_creds"
down_revision: str | None = "20260208_autodownload_nn"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create subsonic_credentials table."""
    if table_exists("subsonic_credentials"):
        return

    op.create_table(
        "subsonic_credentials",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "profile_id",
            sa.Uuid(),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("username", sa.String(100), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("password_token", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Drop subsonic_credentials table."""
    op.drop_table("subsonic_credentials")
