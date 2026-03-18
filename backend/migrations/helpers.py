"""
Shared guard helpers for Alembic migrations.

Migration policy:
- All migrations are one-way (upgrade only). Downgrade functions should use
  ``pass`` unless a reversible operation is specifically required and tested.
- Always use the guard helpers below to make upgrade() idempotent so that
  re-running ``alembic upgrade head`` after a partial failure is safe.

Usage in a migration file::

    from migrations.helpers import column_exists, table_exists, index_exists

    def upgrade():
        if not column_exists("tracks", "my_new_col"):
            op.add_column("tracks", sa.Column("my_new_col", sa.Text()))
"""

import sqlalchemy as sa
from alembic import op


def column_exists(table_name: str, column_name: str) -> bool:
    """Check whether *column_name* exists in *table_name*."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ),
        {"table": table_name, "column": column_name},
    )
    return result.fetchone() is not None


def table_exists(table_name: str) -> bool:
    """Check whether *table_name* exists in the public schema."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = :table"
        ),
        {"table": table_name},
    )
    return result.fetchone() is not None


def index_exists(index_name: str) -> bool:
    """Check whether *index_name* exists."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT indexname FROM pg_indexes WHERE indexname = :name"
        ),
        {"name": index_name},
    )
    return result.fetchone() is not None


def constraint_exists(table_name: str, constraint_name: str) -> bool:
    """Check whether *constraint_name* exists on *table_name*."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT constraint_name FROM information_schema.table_constraints "
            "WHERE table_name = :table AND constraint_name = :constraint"
        ),
        {"table": table_name, "constraint": constraint_name},
    )
    return result.fetchone() is not None
