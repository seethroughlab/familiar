"""Tests for the auto-proposal scanner (auto_proposals.py)."""

import pytest
from sqlalchemy import delete, select

from app.services.auto_proposals import (
    find_duplicate_artist_groups,
    normalize_artist_for_comparison,
    scan_for_duplicate_artist_proposals,
)


class TestNormalizeArtist:
    def test_case_and_separators(self):
        assert normalize_artist_for_comparison("The_Beatles") == "the beatles"
        assert normalize_artist_for_comparison("THE BEATLES") == "the beatles"
        assert normalize_artist_for_comparison("the-beatles") == "the beatles"

    def test_conjunctions(self):
        assert normalize_artist_for_comparison("Simon & Garfunkel") == "simon and garfunkel"
        assert normalize_artist_for_comparison("Simon + Garfunkel") == "simon and garfunkel"

    def test_blank(self):
        assert normalize_artist_for_comparison("") == ""
        assert normalize_artist_for_comparison("   ") == ""


class TestFindDuplicateGroups:
    def test_groups_variants_and_picks_most_common_as_canonical(self):
        artists = [
            ("The Beatles", 30),
            ("the_beatles", 3),
            ("Radiohead", 20),  # no duplicate
        ]
        groups = find_duplicate_artist_groups(artists)
        assert len(groups) == 1
        assert groups[0]["canonical"] == "The Beatles"  # most tracks wins
        names = {v[0] for v in groups[0]["variants"]}
        assert names == {"The Beatles", "the_beatles"}

    def test_no_duplicates_returns_empty(self):
        groups = find_duplicate_artist_groups([("A", 1), ("B", 2), ("C", 3)])
        assert groups == []

    def test_sorted_by_total_tracks_desc(self):
        artists = [
            ("Small", 2), ("small", 1),         # total 3
            ("Big Band", 50), ("big band", 10),  # total 60
        ]
        groups = find_duplicate_artist_groups(artists)
        assert [g["canonical"] for g in groups] == ["Big Band", "Small"]


@pytest.mark.asyncio
async def test_scan_creates_and_dedupes_merge_proposals(async_db):
    """End-to-end: variant spellings produce one merge proposal; re-run is a no-op."""
    from app.db.models import ChangeSource, ChangeStatus, ProposedChange
    from tests.factories import insert_test_track

    # Proposed changes aren't in the fixture cleanup set — clear them ourselves.
    await async_db.execute(delete(ProposedChange))
    await async_db.commit()

    # Canonical "The Beatles" (3 tracks) + one variant "the_beatles" (1 track).
    for i in range(3):
        await insert_test_track(async_db, artist="The Beatles", title=f"A{i}")
    await insert_test_track(async_db, artist="the_beatles", title="variant")
    await async_db.commit()

    created = await scan_for_duplicate_artist_proposals(async_db)
    assert created == 1

    proposals = (
        await async_db.execute(
            select(ProposedChange).where(ProposedChange.status == ChangeStatus.PENDING)
        )
    ).scalars().all()
    assert len(proposals) == 1
    p = proposals[0]
    assert p.field == "artist"
    assert p.new_value == "The Beatles"
    assert p.old_value == "the_beatles"
    assert p.source == ChangeSource.AUTO_ENRICHMENT
    assert len(p.target_ids) == 1

    # Idempotent: running again must not create a duplicate proposal.
    created_again = await scan_for_duplicate_artist_proposals(async_db)
    assert created_again == 0

    await async_db.execute(delete(ProposedChange))
    await async_db.commit()
