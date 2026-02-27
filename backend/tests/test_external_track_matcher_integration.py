"""Integration tests for ExternalTrackMatcher against real PostgreSQL.

Tests the core matching logic (_find_match, match_external_track,
match_new_local_track, rematch_all_unmatched) with real data.
"""

import pytest

from app.services.external_track_matcher import ExternalTrackMatcher
from tests.factories import (
    insert_test_external_track,
    insert_test_playlist,
    insert_test_playlist_track,
    insert_test_profile,
    insert_test_track,
)


@pytest.fixture
async def profile(async_db):
    p = await insert_test_profile(async_db)
    await async_db.commit()
    return p


@pytest.fixture
def matcher(async_db):
    return ExternalTrackMatcher(db=async_db)


class TestMatchByISRC:
    @pytest.mark.asyncio
    async def test_isrc_match(self, async_db, matcher):
        track = await insert_test_track(
            async_db, title="ISRC Song", artist="ISRC Artist", isrc="USRC12345678"
        )
        ext = await insert_test_external_track(
            async_db, title="ISRC Song", artist="ISRC Artist", isrc="USRC12345678"
        )
        await async_db.commit()

        result = await matcher.match_external_track(ext)
        assert result is not None
        assert result.id == track.id
        assert ext.match_method == "isrc"
        assert ext.match_confidence == 1.0


class TestMatchByExactTitleArtist:
    @pytest.mark.asyncio
    async def test_exact_match(self, async_db, matcher):
        track = await insert_test_track(async_db, title="Exact Song", artist="Exact Artist")
        ext = await insert_test_external_track(
            async_db, title="Exact Song", artist="Exact Artist"
        )
        await async_db.commit()

        result = await matcher.match_external_track(ext)
        assert result is not None
        assert result.id == track.id
        assert ext.match_method == "exact"
        assert ext.match_confidence == 1.0


class TestMatchByFuzzy:
    @pytest.mark.asyncio
    async def test_fuzzy_match(self, async_db, matcher):
        await insert_test_track(
            async_db, title="Bohemian Rhapsody", artist="Queen"
        )
        ext = await insert_test_external_track(
            async_db, title="Bohemian Rhapsody (Remastered 2011)", artist="Queen"
        )
        await async_db.commit()

        result = await matcher.match_external_track(ext)
        # This may match via partial or fuzzy depending on normalization
        assert result is not None
        assert ext.match_method in ("exact", "exact_normalized", "partial", "fuzzy")


class TestNoMatch:
    @pytest.mark.asyncio
    async def test_no_match(self, async_db, matcher):
        await insert_test_track(async_db, title="Completely Different", artist="Other Band")
        ext = await insert_test_external_track(
            async_db, title="Unique Title XYZ", artist="Unknown Artist ABC"
        )
        await async_db.commit()

        result = await matcher.match_external_track(ext)
        assert result is None
        assert ext.matched_track_id is None


class TestMatchNewLocalTrack:
    @pytest.mark.asyncio
    async def test_match_new_local_via_isrc(self, async_db, matcher):
        await insert_test_external_track(
            async_db, title="ISRC Match", artist="Band", isrc="GBAYE1234567"
        )
        await async_db.commit()

        track = await insert_test_track(
            async_db, title="ISRC Match", artist="Band", isrc="GBAYE1234567"
        )
        await async_db.commit()

        matched = await matcher.match_new_local_track(track)
        assert len(matched) >= 1
        assert matched[0].match_method == "isrc"


class TestReplaceInPlaylists:
    @pytest.mark.asyncio
    async def test_playlist_track_updated_on_match(self, async_db, profile, matcher):
        ext = await insert_test_external_track(async_db, title="Replace Me", artist="Band")
        playlist = await insert_test_playlist(async_db, profile.id)
        await insert_test_playlist_track(
            async_db, playlist.id, external_track_id=ext.id, position=0
        )
        track = await insert_test_track(async_db, title="Replace Me", artist="Band")
        await async_db.commit()

        await matcher.match_external_track(ext)

        # Verify PlaylistTrack was updated
        from sqlalchemy import select

        from app.db.models import PlaylistTrack
        result = await async_db.execute(
            select(PlaylistTrack).where(PlaylistTrack.playlist_id == playlist.id)
        )
        pt = result.scalar_one()
        assert pt.track_id == track.id
        assert pt.external_track_id is None


class TestManualMatchAndRemove:
    @pytest.mark.asyncio
    async def test_manual_match(self, async_db, matcher):
        track = await insert_test_track(async_db, title="Manual Target", artist="A")
        ext = await insert_test_external_track(async_db, title="Manual Source", artist="B")
        await async_db.commit()

        result = await matcher.manual_match(ext.id, track.id)
        assert result is not None
        assert result.matched_track_id == track.id
        assert result.match_method == "manual"
        assert result.match_confidence == 1.0

    @pytest.mark.asyncio
    async def test_remove_match(self, async_db, matcher):
        track = await insert_test_track(async_db, title="Remove Target", artist="A")
        ext = await insert_test_external_track(
            async_db, title="Remove Source", artist="B", matched_track_id=track.id
        )
        await async_db.commit()

        result = await matcher.remove_match(ext.id)
        assert result is not None
        assert result.matched_track_id is None
        assert result.match_method is None


class TestRematchAllUnmatched:
    @pytest.mark.asyncio
    async def test_rematch_bulk(self, async_db, matcher):
        await insert_test_track(async_db, title="Bulk Song", artist="Bulk Artist")
        await insert_test_external_track(
            async_db, title="Bulk Song", artist="Bulk Artist"
        )
        await insert_test_external_track(
            async_db, title="No Match Here", artist="Unknown999"
        )
        await async_db.commit()

        stats = await matcher.rematch_all_unmatched()
        assert stats["processed"] == 2
        assert stats["matched"] >= 1


class TestFindMatchCandidates:
    @pytest.mark.asyncio
    async def test_isrc_match_first_with_confidence_1(self, async_db, matcher):
        track = await insert_test_track(
            async_db, title="ISRC Candidate", artist="Artist", isrc="USRC99990001"
        )
        await async_db.commit()

        candidates = await matcher.find_match_candidates(
            title="ISRC Candidate", artist="Artist", isrc="USRC99990001"
        )
        assert len(candidates) >= 1
        assert candidates[0]["track_id"] == str(track.id)
        assert candidates[0]["match_method"] == "isrc"
        assert candidates[0]["confidence"] == 1.0

    @pytest.mark.asyncio
    async def test_exact_match_found(self, async_db, matcher):
        track = await insert_test_track(
            async_db, title="Exact Candidate", artist="Exact Band"
        )
        await async_db.commit()

        candidates = await matcher.find_match_candidates(
            title="Exact Candidate", artist="Exact Band"
        )
        assert len(candidates) >= 1
        assert candidates[0]["track_id"] == str(track.id)
        assert candidates[0]["match_method"] == "exact"

    @pytest.mark.asyncio
    async def test_fuzzy_below_normal_threshold_included(self, async_db, matcher):
        """Candidates with 50-85% similarity should appear (below auto-match threshold)."""
        track = await insert_test_track(
            async_db, title="Stairway to Heaven", artist="Led Zeppelin"
        )
        await async_db.commit()

        # Use a somewhat different name that won't hit 85% but should hit 50%
        candidates = await matcher.find_match_candidates(
            title="Stairway to Heaven (Live)", artist="Led Zeppelin"
        )
        assert len(candidates) >= 1
        found = [c for c in candidates if c["track_id"] == str(track.id)]
        assert len(found) == 1

    @pytest.mark.asyncio
    async def test_deduplication_across_methods(self, async_db, matcher):
        """A track matched by ISRC should not appear again in fuzzy results."""
        track = await insert_test_track(
            async_db, title="Dedup Song", artist="Dedup Artist", isrc="GBDUP0000001"
        )
        await async_db.commit()

        candidates = await matcher.find_match_candidates(
            title="Dedup Song", artist="Dedup Artist", isrc="GBDUP0000001"
        )
        track_ids = [c["track_id"] for c in candidates]
        assert track_ids.count(str(track.id)) == 1

    @pytest.mark.asyncio
    async def test_limit_respected(self, async_db, matcher):
        for i in range(5):
            await insert_test_track(
                async_db, title=f"Limit Song {i}", artist="Same Artist"
            )
        await async_db.commit()

        candidates = await matcher.find_match_candidates(
            title="Limit Song", artist="Same Artist", limit=3
        )
        assert len(candidates) <= 3

    @pytest.mark.asyncio
    async def test_empty_title_artist_returns_isrc_only(self, async_db, matcher):
        track = await insert_test_track(
            async_db, title="ISRC Only", artist="Artist", isrc="USRC88880001"
        )
        await async_db.commit()

        candidates = await matcher.find_match_candidates(
            title="", artist="", isrc="USRC88880001"
        )
        assert len(candidates) == 1
        assert candidates[0]["track_id"] == str(track.id)
        assert candidates[0]["match_method"] == "isrc"

    @pytest.mark.asyncio
    async def test_no_title_no_artist_no_isrc_returns_empty(self, async_db, matcher):
        await insert_test_track(async_db, title="Something", artist="Someone")
        await async_db.commit()

        candidates = await matcher.find_match_candidates(title="", artist="")
        assert candidates == []


class TestCreateDedupesBySpotifyId:
    @pytest.mark.asyncio
    async def test_returns_existing_on_duplicate_spotify_id(self, async_db, matcher):
        ext1 = await matcher.create_external_track(
            title="Song", artist="Artist", spotify_id="sp_123", try_match=False
        )
        ext2 = await matcher.create_external_track(
            title="Song v2", artist="Artist v2", spotify_id="sp_123", try_match=False
        )
        assert ext1.id == ext2.id
        assert ext2.title == "Song"  # Original preserved
