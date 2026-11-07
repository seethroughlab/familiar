"""The lookup, against a fake LRCLIB. An outage must never read as "no lyrics" (ADR-0163)."""

import httpx
import pytest

from app.services.lyrics import LyricsService, LyricsStatus

SYNCED = {"id": 1, "syncedLyrics": "[00:01.00]line", "plainLyrics": "line", "duration": 200}
PLAIN = {"id": 2, "syncedLyrics": None, "plainLyrics": "words", "duration": 200}


class FakeLrclib:
    def __init__(self, gets=None, search=None):
        self.gets = list(gets or [])
        self.search = search if search is not None else []
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if request.url.path.endswith("/search"):
            return self.search if isinstance(self.search, httpx.Response) else httpx.Response(
                200, json=self.search
            )
        return self.gets.pop(0) if self.gets else httpx.Response(404, json={})

    def paths(self) -> list[str]:
        return [call.url.path.rsplit("/", 1)[-1] for call in self.calls]


def service(fake: FakeLrclib) -> LyricsService:
    return LyricsService(transport=httpx.MockTransport(fake), min_interval=0)


def candidate(name="Song", artist="Band", duration=200, synced=True, **extra):
    return {
        "id": 9, "trackName": name, "artistName": artist, "duration": duration,
        "syncedLyrics": "[00:01.00]line" if synced else None, "plainLyrics": "line", **extra,
    }


@pytest.mark.asyncio
async def test_an_exact_synced_hit_takes_one_call():
    fake = FakeLrclib(gets=[httpx.Response(200, json=SYNCED)])
    outcome = await service(fake).resolve("Song", "Band", "Album", 200)
    assert outcome.status == LyricsStatus.FOUND
    assert outcome.result.source_id == "lrclib:1"
    assert fake.paths() == ["get"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 500, 503])
async def test_a_failing_server_is_unavailable_and_stops_the_ladder(status):
    fake = FakeLrclib(gets=[httpx.Response(status)])
    outcome = await service(fake).resolve("Song", "Band", None, 200)
    assert outcome.status == LyricsStatus.UNAVAILABLE
    assert fake.paths() == ["get"]


@pytest.mark.asyncio
async def test_a_timeout_is_unavailable():
    def handler(_):
        raise httpx.ReadTimeout("slow")

    outcome = await LyricsService(transport=httpx.MockTransport(handler), min_interval=0).resolve(
        "Song", "Band", None, 200
    )
    assert outcome.status == LyricsStatus.UNAVAILABLE


@pytest.mark.asyncio
async def test_retry_after_stops_every_later_lookup():
    fake = FakeLrclib(gets=[httpx.Response(429, headers={"Retry-After": "120"})])
    lyrics = service(fake)
    await lyrics.resolve("Song", "Band", None, 200)
    later = await lyrics.resolve("Other", "Band", None, 200)
    assert later.status == LyricsStatus.UNAVAILABLE
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_a_404_everywhere_is_a_miss():
    outcome = await service(FakeLrclib()).resolve("Song", "Band", None, 200)
    assert outcome.status == LyricsStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_instrumental_is_an_answer_and_ends_the_lookup():
    # Was: discarded, then `/search`, which could return another song's lyrics.
    fake = FakeLrclib(gets=[httpx.Response(200, json={"id": 3, "instrumental": True})])
    outcome = await service(fake).resolve("Song", "Band", None, 200)
    assert outcome.status == LyricsStatus.INSTRUMENTAL
    assert fake.paths() == ["get"]


@pytest.mark.asyncio
async def test_plain_is_kept_while_search_is_given_a_chance_at_synced():
    fake = FakeLrclib(gets=[httpx.Response(200, json=PLAIN)], search=[candidate()])
    outcome = await service(fake).resolve("Song", "Band", None, 200)
    assert outcome.status == LyricsStatus.FOUND
    assert fake.paths() == ["get", "search"]


@pytest.mark.asyncio
async def test_plain_survives_a_search_failure():
    fake = FakeLrclib(gets=[httpx.Response(200, json=PLAIN)], search=httpx.Response(500))
    outcome = await service(fake).resolve("Song", "Band", None, 200)
    assert outcome.status == LyricsStatus.PLAIN_ONLY


@pytest.mark.asyncio
async def test_search_failure_with_nothing_in_hand_is_unavailable_not_a_miss():
    fake = FakeLrclib(search=httpx.Response(503))
    outcome = await service(fake).resolve("Song", "Band", None, 200)
    assert outcome.status == LyricsStatus.UNAVAILABLE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        candidate(name="A Different Song"),
        candidate(artist="Someone Else"),
        # "Saké (Blackjoy Version)" came back 224 s away from its track, as data[0].
        candidate(duration=424),
    ],
)
async def test_search_never_takes_the_first_result_blind(bad):
    outcome = await service(FakeLrclib(search=[bad])).resolve("Song", "Band", None, 200)
    assert outcome.status == LyricsStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_search_prefers_synced_then_the_closer_length():
    results = [
        candidate(duration=200, synced=False, id=1),
        candidate(duration=204, id=2),
        candidate(duration=201, id=3),
    ]
    outcome = await service(FakeLrclib(search=results)).resolve("Song", "Band", None, 200)
    assert outcome.result.source_id == "lrclib:3"


@pytest.mark.asyncio
async def test_search_accepts_a_right_song_four_seconds_out():
    fake = FakeLrclib(search=[candidate(name="I'll Follow The Sun", artist="Beatles", duration=204)])
    outcome = await service(fake).resolve("I'll Follow the Sun", "Beatles", None, 200)
    assert outcome.status == LyricsStatus.FOUND


@pytest.mark.parametrize(
    ("title", "artist", "expected_title", "expected_artist"),
    [
        ("Deuce", "Cardigans, The", "Deuce", "The Cardigans"),
        ("14-Too Long", "Daft Punk", "Too Long", "Daft Punk"),
        ("Song (feat. Someone)", "Band ft. Someone", "Song", "Band"),
        ("Song - 2011 Remaster", "Band", "Song", "Band"),
        ("Song (Remastered 2009)", "Band", "Song", "Band"),
    ],
)
@pytest.mark.asyncio
async def test_metadata_is_tidied_after_the_exact_try(title, artist, expected_title, expected_artist):
    fake = FakeLrclib()
    await service(fake).resolve(title, artist, None, 200)
    second = fake.calls[1].url.params
    assert (second["track_name"], second["artist_name"]) == (expected_title, expected_artist)


@pytest.mark.parametrize(
    "title",
    ["Song (Live)", "Song (Plum Creek Remix)", "Song (Blackjoy Version)", "Song (Instrumental)",
     "1-800-273-8255"],
)
@pytest.mark.asyncio
async def test_what_names_a_different_recording_is_not_stripped(title):
    fake = FakeLrclib()
    await service(fake).resolve(title, "Band", None, 200)
    assert all(call.url.params["track_name"] == title for call in fake.calls)


@pytest.mark.asyncio
async def test_the_ladder_is_at_most_four_calls_and_none_repeated():
    fake = FakeLrclib()
    await service(fake).resolve("Song (feat. A)", "Band & Other feat. A", "Album", 200, "Label Band")
    assert len(fake.calls) == 4
    assert len({str(call.url) for call in fake.calls}) == 4
    assert "album_name" not in fake.calls[1].url.params


@pytest.mark.asyncio
async def test_various_artists_is_never_asked_for():
    fake = FakeLrclib()
    await service(fake).resolve("Song", "Band", "Album", 200, "Various Artists")
    assert not any(call.url.params.get("artist_name") == "Various Artists" for call in fake.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("duration", [None, 0, 3601])
async def test_a_length_lrclib_refuses_is_left_out(duration):
    fake = FakeLrclib()
    await service(fake).resolve("Song", "Band", None, duration)
    assert "duration" not in fake.calls[0].url.params


@pytest.mark.asyncio
async def test_identifies_itself():
    fake = FakeLrclib()
    await service(fake).resolve("Song", "Band", None, 200)
    assert "github.com/seethroughlab/familiar" in fake.calls[0].headers["user-agent"]
