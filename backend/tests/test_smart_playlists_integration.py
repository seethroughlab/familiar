"""Integration tests for SmartPlaylistService against real PostgreSQL.

Tests rule-based query building, condition logic, and service methods
with real data in the database.
"""

from datetime import datetime, timedelta

import pytest

from app.services.smart_playlists import SmartPlaylistService
from tests.factories import (
    insert_test_analysis,
    insert_test_play_history,
    insert_test_profile,
    insert_test_smart_playlist,
    insert_test_track,
)


@pytest.fixture
async def profile(async_db):
    p = await insert_test_profile(async_db)
    await async_db.commit()
    return p


@pytest.fixture
def svc(async_db):
    return SmartPlaylistService(db=async_db)


class TestGenreContainsRule:
    @pytest.mark.asyncio
    async def test_matches_genre(self, async_db, profile, svc):
        await insert_test_track(async_db, genre="Progressive Rock", title="A")
        await insert_test_track(async_db, genre="Jazz", title="B")
        await async_db.commit()

        sp = await insert_test_smart_playlist(
            async_db, profile.id,
            rules=[{"field": "genre", "operator": "contains", "value": "Rock"}],
        )
        await async_db.commit()

        tracks = await svc.get_tracks(sp)
        assert len(tracks) >= 1
        assert all("rock" in (t.genre or "").lower() for t in tracks)


class TestYearBetweenRule:
    @pytest.mark.asyncio
    async def test_year_range(self, async_db, profile, svc):
        await insert_test_track(async_db, year=1985, title="Old")
        await insert_test_track(async_db, year=2010, title="Mid")
        await insert_test_track(async_db, year=2023, title="New")
        await async_db.commit()

        sp = await insert_test_smart_playlist(
            async_db, profile.id,
            rules=[{"field": "year", "operator": "between", "value": [2000, 2020]}],
        )
        await async_db.commit()

        tracks = await svc.get_tracks(sp)
        assert len(tracks) >= 1
        assert all(2000 <= t.year <= 2020 for t in tracks)


class TestEnergyFilterViaAnalysis:
    @pytest.mark.asyncio
    async def test_energy_filter(self, async_db, profile, svc):
        t_high = await insert_test_track(async_db, title="HighEnergy")
        t_low = await insert_test_track(async_db, title="LowEnergy")
        await insert_test_analysis(async_db, t_high.id, {"energy": 0.9})
        await insert_test_analysis(async_db, t_low.id, {"energy": 0.2})
        await async_db.commit()

        sp = await insert_test_smart_playlist(
            async_db, profile.id,
            rules=[{"field": "energy", "operator": "greater_or_equal", "value": 0.7}],
        )
        await async_db.commit()

        tracks = await svc.get_tracks(sp)
        assert len(tracks) >= 1
        titles = [t.title for t in tracks]
        assert "HighEnergy" in titles
        assert "LowEnergy" not in titles


class TestPlayCountRule:
    @pytest.mark.asyncio
    async def test_play_count_filter(self, async_db, profile, svc):
        t1 = await insert_test_track(async_db, title="Played5")
        t2 = await insert_test_track(async_db, title="Played1")
        await insert_test_play_history(async_db, profile.id, t1.id, play_count=5)
        await insert_test_play_history(async_db, profile.id, t2.id, play_count=1)
        await async_db.commit()

        sp = await insert_test_smart_playlist(
            async_db, profile.id,
            rules=[{"field": "play_count", "operator": "greater_or_equal", "value": 3}],
        )
        await async_db.commit()

        tracks = await svc.get_tracks(sp)
        assert len(tracks) >= 1
        titles = [t.title for t in tracks]
        assert "Played5" in titles
        assert "Played1" not in titles


class TestNeverPlayedRule:
    @pytest.mark.asyncio
    async def test_never_played(self, async_db, profile, svc):
        t_played = await insert_test_track(async_db, title="HasPlays")
        await insert_test_track(async_db, title="NeverPlayed")
        await insert_test_play_history(async_db, profile.id, t_played.id, play_count=2)
        await async_db.commit()

        sp = await insert_test_smart_playlist(
            async_db, profile.id,
            rules=[{"field": "never_played", "operator": "equals", "value": True}],
        )
        await async_db.commit()

        tracks = await svc.get_tracks(sp)
        titles = [t.title for t in tracks]
        assert "NeverPlayed" in titles
        assert "HasPlays" not in titles


class TestMatchModeAnyVsAll:
    @pytest.mark.asyncio
    async def test_match_all(self, async_db, profile, svc):
        await insert_test_track(async_db, genre="Rock", year=2020, title="Both")
        await insert_test_track(async_db, genre="Rock", year=1990, title="GenreOnly")
        await insert_test_track(async_db, genre="Jazz", year=2020, title="YearOnly")
        await async_db.commit()

        sp = await insert_test_smart_playlist(
            async_db, profile.id,
            rules=[
                {"field": "genre", "operator": "contains", "value": "Rock"},
                {"field": "year", "operator": "greater_or_equal", "value": 2000},
            ],
            match_mode="all",
        )
        await async_db.commit()

        tracks = await svc.get_tracks(sp)
        titles = [t.title for t in tracks]
        assert "Both" in titles
        assert "GenreOnly" not in titles
        assert "YearOnly" not in titles

    @pytest.mark.asyncio
    async def test_match_any(self, async_db, profile, svc):
        await insert_test_track(async_db, genre="Rock", year=1990, title="GenreMatch")
        await insert_test_track(async_db, genre="Jazz", year=2020, title="YearMatch")
        await insert_test_track(async_db, genre="Classical", year=1970, title="Neither")
        await async_db.commit()

        sp = await insert_test_smart_playlist(
            async_db, profile.id,
            rules=[
                {"field": "genre", "operator": "contains", "value": "Rock"},
                {"field": "year", "operator": "greater_or_equal", "value": 2000},
            ],
            match_mode="any",
        )
        await async_db.commit()

        tracks = await svc.get_tracks(sp)
        titles = [t.title for t in tracks]
        assert "GenreMatch" in titles
        assert "YearMatch" in titles


class TestMaxTracksLimit:
    @pytest.mark.asyncio
    async def test_max_tracks(self, async_db, profile, svc):
        for i in range(5):
            await insert_test_track(async_db, genre="LimitTest", title=f"LimitTrack{i}")
        await async_db.commit()

        sp = await insert_test_smart_playlist(
            async_db, profile.id,
            rules=[{"field": "genre", "operator": "equals", "value": "LimitTest"}],
            max_tracks=3,
        )
        await async_db.commit()

        tracks = await svc.get_tracks(sp)
        assert len(tracks) == 3


class TestOrderBy:
    @pytest.mark.asyncio
    async def test_order_by_year(self, async_db, profile, svc):
        await insert_test_track(async_db, year=2020, genre="OrderTest", title="Y2020")
        await insert_test_track(async_db, year=2010, genre="OrderTest", title="Y2010")
        await insert_test_track(async_db, year=2015, genre="OrderTest", title="Y2015")
        await async_db.commit()

        sp = await insert_test_smart_playlist(
            async_db, profile.id,
            rules=[{"field": "genre", "operator": "equals", "value": "OrderTest"}],
            order_by="year",
            order_direction="asc",
        )
        await async_db.commit()

        tracks = await svc.get_tracks(sp)
        years = [t.year for t in tracks]
        assert years == sorted(years)

    @pytest.mark.asyncio
    async def test_order_by_play_count(self, async_db, profile, svc):
        t1 = await insert_test_track(async_db, genre="PCOrder", title="P10")
        t2 = await insert_test_track(async_db, genre="PCOrder", title="P1")
        await insert_test_play_history(async_db, profile.id, t1.id, play_count=10)
        await insert_test_play_history(async_db, profile.id, t2.id, play_count=1)
        await async_db.commit()

        # Must include a play_history field in rules to trigger the JOIN
        sp = await insert_test_smart_playlist(
            async_db, profile.id,
            rules=[
                {"field": "genre", "operator": "equals", "value": "PCOrder"},
                {"field": "play_count", "operator": "greater_or_equal", "value": 0},
            ],
            order_by="play_count",
            order_direction="desc",
        )
        await async_db.commit()

        tracks = await svc.get_tracks(sp)
        assert tracks[0].title == "P10"


class TestStringContainsCaseInsensitive:
    @pytest.mark.asyncio
    async def test_ilike_behavior(self, async_db, profile, svc):
        await insert_test_track(async_db, genre="Alt-Rock", title="CaseTest")
        await async_db.commit()

        sp = await insert_test_smart_playlist(
            async_db, profile.id,
            rules=[{"field": "genre", "operator": "contains", "value": "alt-rock"}],
        )
        await async_db.commit()

        tracks = await svc.get_tracks(sp)
        assert len(tracks) >= 1
        assert tracks[0].title == "CaseTest"


class TestLastPlayedInTheLast:
    @pytest.mark.asyncio
    async def test_in_the_last(self, async_db, profile, svc):
        t_recent = await insert_test_track(async_db, title="RecentPlay")
        t_old = await insert_test_track(async_db, title="OldPlay")
        await insert_test_play_history(
            async_db, profile.id, t_recent.id,
            last_played_at=datetime.utcnow() - timedelta(days=2),
        )
        await insert_test_play_history(
            async_db, profile.id, t_old.id,
            last_played_at=datetime.utcnow() - timedelta(days=60),
        )
        await async_db.commit()

        sp = await insert_test_smart_playlist(
            async_db, profile.id,
            rules=[{
                "field": "last_played_at",
                "operator": "in_the_last",
                "value": {"amount": 7, "unit": "days"},
            }],
        )
        await async_db.commit()

        tracks = await svc.get_tracks(sp)
        titles = [t.title for t in tracks]
        assert "RecentPlay" in titles
        assert "OldPlay" not in titles


class TestRefreshUpdatesCachedCount:
    @pytest.mark.asyncio
    async def test_refresh(self, async_db, profile, svc):
        await insert_test_track(async_db, genre="RefreshTest", title="R1")
        await insert_test_track(async_db, genre="RefreshTest", title="R2")
        await async_db.commit()

        sp = await insert_test_smart_playlist(
            async_db, profile.id,
            rules=[{"field": "genre", "operator": "equals", "value": "RefreshTest"}],
        )
        await async_db.commit()

        count = await svc.refresh_playlist(sp)
        assert count == 2
        assert sp.cached_track_count == 2
