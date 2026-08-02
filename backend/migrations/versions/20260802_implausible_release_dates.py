"""Clear cached release dates that cannot be true.

Two of 589 rows in `external_album_cache` claimed release dates of **2913** and **2209** — year-only
dates from MusicBrainz with a digit typed wrong. They parse cleanly, so nothing rejected them on the
way in, and because the new-releases list is ordered by `release_date DESC NULLS LAST` they sorted
above every real release. The two most prominent cards in Discover were the two worst rows in the
table.

`plausible_release_date` now rejects these at ingestion, but that alone would never heal these rows:
`save_discovered_release` returns early when a `release_id` already exists and never updates it, so
a bad row is permanent until something rewrites it. This is that something.

The date is cleared rather than the row deleted. These are real compilations with a typo attached —
keeping them discoverable while dropping the claim that is wrong is the smaller loss, and
`NULLS LAST` then stops them leading a list called "new releases".

Only the future bound is checked, matching the helper: an old first-release date can legitimately
belong to a reissue, and that is a different question.

Revision ID: 20260802_bad_release_dates
Revises: 20260727_playback_sessions
Create Date: 2026-08-02
"""

from collections.abc import Sequence

from alembic import op

from migrations.helpers import column_exists, table_exists

revision: str = "20260802_bad_release_dates"
down_revision: str | None = "20260727_playback_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not table_exists("external_album_cache"):
        return
    if not column_exists("external_album_cache", "release_date"):
        return

    # The same 366-day window `plausible_release_date` uses. Written as an interval rather than a
    # literal year so a migration run later does not clear dates the application would keep.
    op.execute(
        """
        UPDATE external_album_cache
        SET release_date = NULL
        WHERE release_date IS NOT NULL
          AND release_date > (NOW() + INTERVAL '366 days')
        """
    )


def downgrade() -> None:
    # One-way: the cleared values were wrong and there is nowhere to restore them from — the source
    # they came from is the thing that had them wrong. Re-running the new-releases sync repopulates
    # dates for anything MusicBrainz can still answer for, now filtered.
    pass
