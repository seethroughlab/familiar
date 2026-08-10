"""Make spotify_imports.imported_at NOT NULL, as the model has always said.

`SpotifyImport.imported_at` is `Mapped[datetime]` — not `Mapped[datetime | None]` — so the model
declares NOT NULL. `20260309_spotify_imports.py` created the column with a `server_default` but no
`nullable=False`, and in SQLAlchemy a `Column` without `nullable` is nullable.

**Nothing caught this for five months**, because the only guard was
`test_models_in_sync_with_migrations`, which runs `alembic check` against a freshly migrated
database — and the baseline migration builds fresh databases with `Base.metadata.create_all()`, so
their schema comes from the models rather than from this DDL. The two never disagreed *there*. On
the production database, which got the column from the migration, `imported_at` is nullable.

The replacement test in `tests/test_migrations.py` is what would have caught it.

Revision ID: 20260810_spotify_imported_at_nn
Revises: 20260802_bad_release_dates
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import column_exists, table_exists

revision: str = "20260810_spotify_imported_at_nn"
down_revision: str | None = "20260802_bad_release_dates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not (table_exists("spotify_imports") and column_exists("spotify_imports", "imported_at")):
        return

    # Backfill before tightening. The `server_default` means rows written through the app always
    # have a value, but a row inserted with an explicit NULL would block the ALTER — and failing a
    # deploy over one nullable timestamp is a worse outcome than stamping it with now().
    op.execute(
        sa.text("UPDATE spotify_imports SET imported_at = now() WHERE imported_at IS NULL")
    )
    op.alter_column(
        "spotify_imports",
        "imported_at",
        existing_type=sa.DateTime(timezone=True),
        existing_server_default=sa.text("now()"),
        nullable=False,
    )


def downgrade() -> None:
    # One-way: widening the column back to nullable would restore the defect, and nothing can be
    # written that depends on it being nullable in between.
    pass
