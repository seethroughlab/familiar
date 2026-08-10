"""Drop spotify_imports — the favorites import is retired.

The Spotify favorites import parsed a Spotify data export, matched its tracks against the local
library, and let you browse what was missing. It has been unreachable from the app for some time:
`SpotifyImportModal` rendered only when `spotifyImportFile` was non-null, and the only call to
`setSpotifyImportFile` passed `null`, from `onClose`. Nothing ever opened it.

The table holds a parsed export and its match results — a cache of a file the user still has, not
original data. Dropping it is the point of retiring the feature rather than leaving a table nothing
writes to.

Revision ID: 20260810_drop_spotify_imports
Revises: 20260810_spotify_imported_at_nn
Create Date: 2026-08-10
"""

from collections.abc import Sequence

from alembic import op

from migrations.helpers import table_exists

revision: str = "20260810_drop_spotify_imports"
down_revision: str | None = "20260810_spotify_imported_at_nn"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if table_exists("spotify_imports"):
        op.drop_table("spotify_imports")


def downgrade() -> None:
    # One-way: the table's contents are a derived cache of a Spotify export file, and nothing
    # remains that could read or repopulate it.
    pass
