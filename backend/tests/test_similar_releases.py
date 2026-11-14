"""ADR-0180: new releases by artists similar to the ones a profile plays."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.db.models import Artist, ArtistAlias, ProfilePlayHistory, ProfileReleaseReason, Track, TrackStatus
from app.services.discovery import similar_releases as sr
from app.utils.time import utcnow
from tests.conftest import make_profile_headers

NOW = datetime(2026, 11, 14, 12, 0)
BONOBO = "9a709693-b4f8-4da9-8cc1-038c911a61be"


def _similar(name: str, mbid: str, match: float) -> dict:
    return {"name": name, "mbid": mbid, "match": str(match)}


def _release(**overrides) -> dict:
    release = {
        "release_group_primary_type": "Album",
        "release_group_mbid": f"rg-{uuid4().hex[:8]}",
        "artist_mbids": [BONOBO],
        "artist_credit_name": "Bonobo",
        "release_name": "Fragments II",
        "release_date": (NOW - timedelta(days=3)).date().isoformat(),
        "caa_release_mbid": None,
    }
    release.update(overrides)
    return release


class TestCandidates:
    def _pick(self, similar, *, names=frozenset(), mbids=frozenset()):
        return sr.candidates_from_similar(
            seed_artist_id=None, seed_name="Tycho", similar=similar,
            library_names=set(names), library_mbids=set(mbids),
        )

    def test_close_unowned_artists_with_an_id_are_kept_closest_first(self):
        picked = self._pick([
            _similar("Boards of Canada", "boc", 0.5),
            _similar("Bonobo", BONOBO, 0.9),
            _similar("Too Far", "far", 0.1),
            _similar("No Id", "", 0.95),
        ])
        assert [c.name for c in picked] == ["Bonobo", "Boards of Canada"]

    def test_artists_already_in_the_library_are_left_out(self):
        picked = self._pick(
            [_similar("Bonobo", BONOBO, 0.9), _similar("Emancipator", "em", 0.8)],
            names={"emancipator"}, mbids={BONOBO},
        )
        assert picked == []

    def test_at_most_ten_per_seed(self):
        picked = self._pick([_similar(f"A{i}", f"m{i}", 0.5) for i in range(15)])
        assert len(picked) == sr.SIMILAR_PER_ARTIST


class TestSelect:
    candidate = sr.Candidate(BONOBO, "Bonobo", None, "Tycho", 0.9)

    def _select(self, *releases):
        return sr.select_for_similar(list(releases), {BONOBO: self.candidate}, now=NOW)

    def test_a_fresh_album_by_a_similar_artist_is_chosen(self):
        [(item, candidate)] = self._select(_release())
        assert item["artist_name"] == "Bonobo" and item["release_type"] == "album"
        assert candidate.seed_name == "Tycho"

    def test_releases_that_are_not_new_music_by_that_artist_are_not(self):
        assert self._select(
            _release(release_date=(NOW - timedelta(days=40)).date().isoformat()),  # not fresh
            _release(release_date=None),  # undated
            _release(artist_credit_name="Somebody Else"),  # the mbid is wrong: names disagree
            _release(artist_mbids=[BONOBO, "89ad4ac3-39f7-470e-963a-56509c546377"]),  # VA
            _release(release_group_mbid=None),
            _release(release_group_primary_type="Broadcast"),
        ) == []


def _track(artist_id, file: str) -> Track:
    return Track(
        id=uuid4(), file_path=f"/music/{file}.mp3", file_hash=f"h-{file}", title=file,
        artist="Tycho", canonical_artist_id=artist_id, status=TrackStatus.ACTIVE,
    )


@pytest.mark.asyncio
async def test_a_profile_gets_its_similar_artists_releases_and_another_does_not(async_db, client, test_profile):
    listener = UUID(test_profile["id"])
    other = client.post("/api/v1/profiles", json={"name": f"Other {uuid4().hex[:8]}"}).json()

    tycho = Artist(name="Tycho", sort_name="Tycho", similar_artists=[_similar("Bonobo", BONOBO, 0.9)])
    async_db.add(tycho)
    await async_db.flush()
    async_db.add(ArtistAlias(alias_normalized="tycho", alias="Tycho", artist_id=tycho.id, source="tag"))
    track = _track(tycho.id, "awake")
    async_db.add(track)
    await async_db.flush()
    async_db.add(ProfilePlayHistory(profile_id=listener, track_id=track.id, play_count=42))
    await async_db.commit()

    # The listener's what's-new baseline is taken before anything similar exists.
    client.get("/api/v1/library/discover/whats-new", headers=make_profile_headers(test_profile))

    now = utcnow().replace(tzinfo=None)
    release = _release(release_date=(now - timedelta(days=2)).date().isoformat())
    stats = await sr.match_similar_releases(async_db, [release], now=now)

    assert stats["similar_new"] == 1 and stats["profiles_told"] == [str(listener)]
    reason = (await async_db.execute(select(ProfileReleaseReason))).scalar_one()
    assert (reason.profile_id, reason.seed_artist_name) == (listener, "Tycho")

    again = await sr.match_similar_releases(async_db, [release], now=now)
    assert again["similar_new"] == 0, "the same release is not new twice"

    mine = client.get("/api/v1/library/discover/whats-new", headers=make_profile_headers(test_profile)).json()
    theirs = client.get("/api/v1/library/discover/whats-new", headers=make_profile_headers(other)).json()
    [item] = [i for i in mine["items"] if i["artist_name"] == "Bonobo"]
    assert item["is_new"] and mine["new_count"] == 1
    assert item["reason"] == {
        "kind": "similar_artist", "text": "Similar to Tycho, which you play",
        "seed_artist_name": "Tycho", "play_count": 42,
    }
    assert all(i["artist_name"] != "Bonobo" for i in theirs["items"])


class FakeLastfm:
    def __init__(self):
        self.calls: list[str] = []

    def is_configured(self):
        return True

    async def get_similar_artists(self, name, limit=20):
        self.calls.append(name)
        return [_similar("Bonobo", BONOBO, 0.9)]


@pytest.mark.asyncio
async def test_warming_fills_played_artists_within_budget_and_leaves_fetched_at(async_db, test_profile, monkeypatch):
    listener = UUID(test_profile["id"])
    for i in range(3):
        artist = Artist(name=f"Played {i}", sort_name=f"Played {i}")
        async_db.add(artist)
        await async_db.flush()
        track = _track(artist.id, f"t{i}")
        async_db.add(track)
        await async_db.flush()
        async_db.add(ProfilePlayHistory(profile_id=listener, track_id=track.id, play_count=10 - i))
    await async_db.commit()

    lastfm = FakeLastfm()
    monkeypatch.setattr("app.services.lastfm.get_lastfm_service", lambda: lastfm)
    result = await sr.run_similar_artists_warm(budget=2)

    assert result["warmed"] == 2 and lastfm.calls == ["Played 0", "Played 1"]
    rows = (await async_db.execute(select(Artist).where(Artist.name.like("Played %")).execution_options(populate_existing=True))).scalars().all()
    warmed = {a.name: a for a in rows}
    assert warmed["Played 0"].similar_artists and warmed["Played 0"].fetched_at is None
    assert not warmed["Played 2"].similar_artists


@pytest.mark.asyncio
async def test_warming_asks_nothing_when_discovery_is_off(monkeypatch):
    lastfm = FakeLastfm()
    monkeypatch.setattr("app.services.lastfm.get_lastfm_service", lambda: lastfm)
    monkeypatch.setattr("app.services.discovery.source_enabled", lambda source: False)
    assert (await sr.run_similar_artists_warm())["status"] == "disabled"
    assert lastfm.calls == []
