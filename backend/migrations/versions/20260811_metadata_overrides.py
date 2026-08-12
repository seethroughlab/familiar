"""Remember which tag fields a person edited, so a rescan cannot undo them.

`LibraryScanner._update_track` assigns title, artist, album, album_artist, the numbers, year and
genre straight from the file whenever its hash changes. Nothing recorded that a person had corrected
any of them, so re-tagging a file elsewhere — or re-encoding it, or replacing it — silently threw the
correction away.

Deliberately **not** `user_overrides`. That column is documented as overrides for *analysis* values
(`{"bpm": 124.0, "key": "Am"}`) and is merged only where the key already exists in the feature set.
Tag overrides answer a different question — who wins between the library and the file — and mixing
them would make both harder to reason about.

Revision ID: 20260811_metadata_overrides
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import column_exists

revision: str = "20260811_metadata_overrides"
down_revision: str | None = "20260810_drop_spotify_imports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not column_exists("tracks", "metadata_overrides"):
        op.add_column(
            "tracks",
            sa.Column(
                "metadata_overrides",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )


def downgrade() -> None:
    if column_exists("tracks", "metadata_overrides"):
        op.drop_column("tracks", "metadata_overrides")
