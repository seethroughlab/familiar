"""A listener's year, summarised from play events (ADR-0156)."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.db.models import ProfileFavorite
from app.services.recap import RECAP_MIN_PLAYS, compute_recap, recap_window
from tests.conftest import make_profile_headers
from tests.factories import (
    insert_test_analysis,
    insert_test_play_event,
    insert_test_play_history,
    insert_test_profile,
    insert_test_track,
)

UTC = ZoneInfo("UTC")
NOW = datetime(2026, 12, 15)
IN_WINDOW = datetime(2026, 9, 10, 12)


async def _plays(db, profile, track, n, *, at=IN_WINDOW, **kwargs):
    for _ in range(n):
        await insert_test_play_event(db, profile.id, track.id, started_at=at, **kwargs)


# ── The window (point 3) ───────────────────────────────────────────────


def test_2026_starts_at_the_trustworthy_cutoff_not_january():
    """The first recap covers about five months, and says so."""
    start, end = recap_window(2026, UTC, NOW)
    assert start == datetime(2026, 8, 1)
    assert end == NOW


def test_a_full_year_is_read_in_the_listeners_zone():
    """New Year in Tokyo is 15:00 UTC on December 31."""
    start, end = recap_window(2027, ZoneInfo("Asia/Tokyo"), datetime(2028, 6, 1))
    assert start == datetime(2026, 12, 31, 15)
    assert end == datetime(2027, 12, 31, 15)


@pytest.mark.parametrize("year", [2025, 2030])
def test_a_year_with_no_trustworthy_data_is_an_empty_window_not_an_inverted_one(year):
    start, end = recap_window(year, UTC, NOW)
    assert start == end


# ── What is counted (points 2, 4, 5) ───────────────────────────────────


@pytest.mark.asyncio
async def test_only_events_inside_the_window_are_counted(async_db):
    profile = await insert_test_profile(async_db)
    track = await insert_test_track(async_db)
    await _plays(async_db, profile, track, 3)
    await _plays(async_db, profile, track, 4, at=datetime(2026, 7, 30))  # before the cutoff
    await _plays(async_db, profile, track, 5, at=datetime(2027, 1, 2))  # next year
    await async_db.commit()

    recap = await compute_recap(async_db, profile.id, 2026, UTC, now=datetime(2027, 2, 1))

    assert recap.plays == 3


@pytest.mark.asyncio
async def test_the_all_time_aggregate_is_never_read(async_db):
    """`ProfilePlayHistory` has no dates; a recap built on it would say "this year" of all time."""
    profile = await insert_test_profile(async_db)
    track = await insert_test_track(async_db)
    await insert_test_play_history(async_db, profile.id, track.id, play_count=500)
    await async_db.commit()

    recap = await compute_recap(async_db, profile.id, 2026, UTC, now=NOW)

    assert recap.plays == 0
    assert recap.top_tracks == []


@pytest.mark.asyncio
async def test_skips_count_as_time_listened_but_not_as_plays_and_errors_as_neither(async_db):
    profile = await insert_test_profile(async_db)
    track = await insert_test_track(async_db)
    await _plays(async_db, profile, track, 1, played_seconds=120)
    await _plays(async_db, profile, track, 1, outcome="skipped", played_seconds=60)
    await _plays(async_db, profile, track, 1, outcome="errored", played_seconds=600)
    await async_db.commit()

    recap = await compute_recap(async_db, profile.id, 2026, UTC, now=NOW)

    assert recap.plays == 1
    assert recap.minutes_listened == 3.0


@pytest.mark.asyncio
async def test_another_profiles_listening_is_not_counted(async_db):
    mine = await insert_test_profile(async_db, name="Mine")
    theirs = await insert_test_profile(async_db, name="Theirs")
    track = await insert_test_track(async_db)
    await _plays(async_db, mine, track, 2)
    await _plays(async_db, theirs, track, 9)
    await async_db.commit()

    recap = await compute_recap(async_db, mine.id, 2026, UTC, now=NOW)

    assert recap.plays == 2


@pytest.mark.asyncio
async def test_too_few_plays_is_insufficient_rather_than_a_thin_recap(async_db):
    profile = await insert_test_profile(async_db)
    track = await insert_test_track(async_db)
    await _plays(async_db, profile, track, RECAP_MIN_PLAYS - 1)
    await async_db.commit()

    thin = await compute_recap(async_db, profile.id, 2026, UTC, now=NOW)
    assert thin.insufficient
    assert thin.plays == RECAP_MIN_PLAYS - 1  # the body is still complete

    await _plays(async_db, profile, track, 1)
    await async_db.commit()
    assert not (await compute_recap(async_db, profile.id, 2026, UTC, now=NOW)).insufficient


# ── Rankings ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ranking_is_by_plays_then_minutes_then_name(async_db):
    profile = await insert_test_profile(async_db)
    most = await insert_test_track(async_db, title="Most", artist="A", album="X")
    longer = await insert_test_track(async_db, title="Zed", artist="B", album="Y")
    alpha = await insert_test_track(async_db, title="Alpha", artist="C", album="Z")
    beta = await insert_test_track(async_db, title="Beta", artist="D", album="W")
    await _plays(async_db, profile, most, 3)
    await _plays(async_db, profile, longer, 2, played_seconds=300)
    await _plays(async_db, profile, beta, 2)
    await _plays(async_db, profile, alpha, 2)
    await async_db.commit()

    recap = await compute_recap(async_db, profile.id, 2026, UTC, now=NOW)

    assert [t.title for t in recap.top_tracks] == ["Most", "Zed", "Alpha", "Beta"]
    assert [a.name for a in recap.top_artists] == ["A", "B", "C", "D"]
    assert recap.top_album.name == "X"
    assert recap.top_album.track_id == most.id


@pytest.mark.asyncio
async def test_artists_are_grouped_by_canonical_artist_across_tracks(async_db):
    profile = await insert_test_profile(async_db)
    one = await insert_test_track(async_db, title="One", artist="Broadcast", album="A")
    two = await insert_test_track(async_db, title="Two", artist="Broadcast", album="B")
    other = await insert_test_track(async_db, title="Three", artist="Stereolab", album="C")
    await _plays(async_db, profile, one, 2)
    await _plays(async_db, profile, two, 2)
    await _plays(async_db, profile, other, 3)
    await async_db.commit()

    recap = await compute_recap(async_db, profile.id, 2026, UTC, now=NOW)

    assert [(a.name, a.plays) for a in recap.top_artists] == [("Broadcast", 4), ("Stereolab", 3)]
    assert recap.unique_artists == 2


@pytest.mark.asyncio
async def test_a_top_track_shows_its_artists_canonical_spelling(async_db):
    """Not "Boards Of Canada" on one slide and "Boards of Canada" on the next."""
    profile = await insert_test_profile(async_db)
    await insert_test_track(async_db, title="Roygbiv", artist="Boards of Canada", album="A")
    track = await insert_test_track(
        async_db, title="All Reason Departs", artist="Boards Of Canada", album="B"
    )
    await _plays(async_db, profile, track, 2)
    await async_db.commit()

    recap = await compute_recap(async_db, profile.id, 2026, UTC, now=NOW)

    assert recap.top_tracks[0].artist == recap.top_artists[0].name == "Boards of Canada"


# ── Time, sound, firsts (point 6) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_the_clock_and_month_are_read_in_the_listeners_zone(async_db):
    """23:30 UTC on Sept 30 is 01:30 on Oct 1 in Berlin."""
    profile = await insert_test_profile(async_db)
    track = await insert_test_track(async_db)
    await _plays(async_db, profile, track, 2, at=datetime(2026, 9, 30, 23, 30))
    await _plays(async_db, profile, track, 1, at=datetime(2026, 9, 10, 12))
    await async_db.commit()

    recap = await compute_recap(async_db, profile.id, 2026, ZoneInfo("Europe/Berlin"), now=NOW)

    assert len(recap.listening_clock) == 24
    assert recap.listening_clock[1] == 2
    assert recap.peak_hour == 1
    assert recap.top_month == 10


@pytest.mark.asyncio
async def test_sound_is_weighted_by_how_often_each_track_was_played(async_db):
    profile = await insert_test_profile(async_db)
    loud = await insert_test_track(async_db, title="Loud")
    quiet = await insert_test_track(async_db, title="Quiet")
    await insert_test_analysis(async_db, loud.id, {
        "bpm": 140.0, "energy": 0.9, "key": "A minor",
        "mood_tags": [
            {"tag": "aggressive", "category": "mood", "confidence": 0.4},
            # Outnumbers both moods; a genre is not a mood, so it must not be counted.
            {"tag": "blues", "category": "genre", "confidence": 0.5},
        ],
    })
    await insert_test_analysis(async_db, quiet.id, {
        "bpm": 70.0, "energy": 0.1, "key": "C major",
        "mood_tags": [
            {"tag": "calm", "category": "mood", "confidence": 0.4},
            {"tag": "blues", "category": "genre", "confidence": 0.5},
        ],
    })
    await _plays(async_db, profile, loud, 3)
    await _plays(async_db, profile, quiet, 1)
    await async_db.commit()

    sound = (await compute_recap(async_db, profile.id, 2026, UTC, now=NOW)).sound

    assert sound.bpm == 140.0
    assert sound.energy == 0.9
    assert sound.key == "A minor"
    assert sound.mood_tags == ["aggressive", "calm"]
    assert sound.valence is None  # unanalysed is absent, not zero


@pytest.mark.asyncio
async def test_a_first_listen_is_a_track_never_heard_before_the_window(async_db):
    """A July play is unreliable about how much was heard, not about whether it was."""
    profile = await insert_test_profile(async_db)
    new = await insert_test_track(async_db, title="New")
    old = await insert_test_track(async_db, title="Old")
    await _plays(async_db, profile, old, 1, at=datetime(2026, 7, 28))
    await _plays(async_db, profile, old, 1)
    await _plays(async_db, profile, new, 1)
    await async_db.commit()

    recap = await compute_recap(async_db, profile.id, 2026, UTC, now=NOW)

    assert recap.first_listens == 1


@pytest.mark.asyncio
async def test_a_track_only_skipped_is_not_a_first_listen(async_db):
    """First listens are a subset of the tracks played, never more of them."""
    profile = await insert_test_profile(async_db)
    played = await insert_test_track(async_db, title="Played")
    skipped = await insert_test_track(async_db, title="Skipped")
    await _plays(async_db, profile, played, 1)
    await _plays(async_db, profile, skipped, 1, outcome="skipped", played_seconds=10)
    await async_db.commit()

    recap = await compute_recap(async_db, profile.id, 2026, UTC, now=NOW)

    assert recap.first_listens == 1
    assert recap.first_listens <= recap.unique_tracks


@pytest.mark.asyncio
async def test_favourites_added_in_the_window_are_counted(async_db):
    profile = await insert_test_profile(async_db)
    kept = await insert_test_track(async_db, title="Kept")
    earlier = await insert_test_track(async_db, title="Earlier")
    async_db.add(ProfileFavorite(profile_id=profile.id, track_id=kept.id, favorited_at=IN_WINDOW))
    async_db.add(ProfileFavorite(
        profile_id=profile.id, track_id=earlier.id, favorited_at=datetime(2026, 3, 1)
    ))
    await async_db.commit()

    recap = await compute_recap(async_db, profile.id, 2026, UTC, now=NOW)

    assert recap.favorites_added == 1


# ── The endpoint ───────────────────────────────────────────────────────


def test_endpoint_returns_the_window_it_summarised(client, test_profile):
    response = client.get(
        "/api/v1/recap/2026?tz=Europe/London", headers=make_profile_headers(test_profile)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["timezone"] == "Europe/London"
    # Midnight on August 1 is the cutoff in naive UTC, whatever the listener's zone.
    assert body["window_start"].startswith("2026-08-01T00:00:00")
    assert body["insufficient"] is True
    assert len(body["listening_clock"]) == 24


def test_endpoint_rejects_an_unknown_time_zone(client, test_profile):
    response = client.get(
        "/api/v1/recap/2026?tz=Mars/Olympus", headers=make_profile_headers(test_profile)
    )
    assert response.status_code == 400


def test_endpoint_requires_a_profile(client):
    assert client.get("/api/v1/recap/2026").status_code == 401


@pytest.mark.asyncio
async def test_the_sound_is_placed_within_the_whole_library(async_db):
    """A raw 0.85 energy is typical of this analysis; the percentile is what a slide can say."""
    profile = await insert_test_profile(async_db)
    played = await insert_test_track(async_db, title="Played")
    await insert_test_analysis(async_db, played.id, {"energy": 0.3, "valence": 0.5})
    # The rest of the library, never played: three tracks above the played one, one below.
    for title, energy in [("A", 0.9), ("B", 0.8), ("C", 0.7), ("D", 0.1)]:
        other = await insert_test_track(async_db, title=title)
        await insert_test_analysis(async_db, other.id, {"energy": energy, "valence": 0.5})
    await _plays(async_db, profile, played, 3)
    await async_db.commit()

    percentile = (await compute_recap(async_db, profile.id, 2026, UTC, now=NOW)).sound.library_percentile

    assert percentile.energy == 30  # one below, itself counted as half, of five
    assert percentile.valence == 50  # level with everything: the middle
    assert percentile.bpm is None  # no median, no rank
