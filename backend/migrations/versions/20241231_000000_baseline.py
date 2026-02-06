"""Baseline migration - creates the initial schema.

For fresh databases: Creates all tables using SQLAlchemy models.
For existing databases: This is stamped without running (tables already exist).

Revision ID: 20241231_000000_baseline
Revises:
Create Date: 2024-12-31 00:00:00
"""
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "20241231_000000_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create all tables from SQLAlchemy models."""
    from app.db.models import Base

    # Create required extensions
    op.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    op.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))

    # Create all tables from models
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    """Drop all tables - use with caution!"""
    from app.db.models import Base

    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
