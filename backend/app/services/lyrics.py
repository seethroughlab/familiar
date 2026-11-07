"""Lyrics fetching service using LRCLIB.net for synced lyrics."""

import asyncio
import logging
import re
import time
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import httpx

logger = logging.getLogger(__name__)

#: LRCLIB asks clients to identify themselves.
USER_AGENT = "Familiar (https://github.com/seethroughlab/familiar)"
#: Familiar's registration at lrclib.net/developers (client-side, 2026-11-07). Public and
#: self-asserted, not a credential: it names the app on LRCLIB's side and backs the shareable
#: authorization document cited in familiar-apple's APP-REVIEW-NOTES.md.
LRCLIB_APP_ID = "mbbWyD6CzJZx2ZTZ75B2y2VX6YjlEGQ_fkdvTu20VaA"
#: LRCLIB asks for sequential requests 200-500 ms apart.
MIN_INTERVAL_SECONDS = 0.3
#: For a 429 with no usable `Retry-After`.
DEFAULT_HOLD_SECONDS = 60.0
#: Wider than LRCLIB's own two seconds: the baseline's right songs included one at four (ADR-0163).
SEARCH_DURATION_TOLERANCE = 5.0

#: Tighter for `Title (a gloss)`, since dropping the parenthesis could otherwise name another song.
GLOSSED_TITLE_DURATION_TOLERANCE = 2.0

_FAILED = object()

_FEATURING_GROUP = re.compile(r"\s*[(\[]\s*(?:feat\.?|ft\.?|featuring)\s[^)\]]*[)\]]", re.IGNORECASE)
_FEATURING_TAIL = re.compile(r"\s+(?:feat\.?|ft\.?|featuring)\s.*$", re.IGNORECASE)
_REMASTER_GROUP = re.compile(r"\s*[(\[][^)\]]*\bremaster(?:ed)?\b[^)\]]*[)\]]", re.IGNORECASE)
_REMASTER_TAIL = re.compile(r"\s+-\s+(?:\d{4}\s+)?(?:digital\s+)?remaster(?:ed)?(?:\s+\d{4})?\s*$", re.IGNORECASE)
#: `14-Too Long`, and only before a letter: `1-800-273-8255` is a title.
_TRACK_NUMBER = re.compile(r"^\d{1,3}\s*[-.]\s*(?=[^\W\d])")
_ARTIST_FEATURING = re.compile(r"\s+(?:feat\.?|ft\.?|featuring)\s", re.IGNORECASE)
_ARTICLE_LAST = re.compile(r"^(.+),\s*(the|a|an)$", re.IGNORECASE)
_ARTIST_JOIN = re.compile(r"\s*(?:&|/|;|,|\band\b)\s*", re.IGNORECASE)
_NON_WORD = re.compile(r"[^\w]+")
_PARENTHETICAL = re.compile(r"\s*[(\[][^)\]]*[)\]]")


@dataclass
class LyricLine:
    """A single line of lyrics with timing."""
    time: float  # Time in seconds
    text: str


@dataclass
class LyricsResult:
    """Result from lyrics search."""
    synced: bool
    lines: list[LyricLine]
    plain_text: str
    source: str = "lrclib"
    source_id: str | None = None


class LyricsStatus(StrEnum):
    """What a lookup amounts to. `UNAVAILABLE` says nothing about the track (ADR-0163 point 6)."""

    FOUND = "found"
    PLAIN_ONLY = "plain_only"
    INSTRUMENTAL = "instrumental"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"


@dataclass
class LyricsOutcome:
    status: LyricsStatus
    result: LyricsResult | None = None


def plain_outcome(result: LyricsResult) -> LyricsOutcome:
    """An outcome for lyrics in hand, whichever kind they are."""
    return LyricsOutcome(LyricsStatus.FOUND if result.synced else LyricsStatus.PLAIN_ONLY, result)


def _retry_after(value: str | None) -> float | None:
    try:
        return max(0.0, float(value)) if value else None
    except ValueError:
        return None


#: One or more leading time tags: `[mm:ss]`, `[mm:ss.xx]`, `[mm:ss.xxx]`, or `[mm:ss:xx]`.
_TIME_TAG = re.compile(r"\[(\d+):(\d{1,2})(?:[.:](\d{1,3}))?\]")
_OFFSET_TAG = re.compile(r"^\[offset:\s*([+-]?\d+)\s*\]\s*$", re.IGNORECASE)
#: Enhanced LRC's per-word timing. Lines are the unit here, so these are only noise in the text.
_WORD_TAG = re.compile(r"<\d+:\d{1,2}(?:[.:]\d{1,3})?>")


def parse_lrc(content: str) -> list[LyricLine]:
    """Parse LRC text into timed lines, earliest first.

    **The fraction is scaled by its own length.** `.34` is 340 ms and `.345` is 345 ms. Dividing every
    fraction by 100 put a three-digit line up to 9.99 s late, and out of order with its neighbours.

    A line can carry several time tags, for a repeated chorus, and is one line per tag. `[offset:]` is
    in milliseconds, and a positive value makes the lyrics come sooner, by the format's definition.
    """
    offset = 0.0
    lines: list[LyricLine] = []

    for raw in content.lstrip("\ufeff").splitlines():
        line = raw.strip()
        offset_match = _OFFSET_TAG.match(line)
        if offset_match:
            offset = int(offset_match.group(1)) / 1000
            continue

        times: list[float] = []
        position = 0
        while match := _TIME_TAG.match(line, position):
            fraction = match.group(3) or ""
            times.append(
                int(match.group(1)) * 60
                + int(match.group(2))
                + (int(fraction) / 10 ** len(fraction) if fraction else 0.0)
            )
            position = match.end()

        text = _WORD_TAG.sub("", line[position:]).strip()
        if text:
            lines.extend(LyricLine(time=time, text=text) for time in times)

    return sorted(
        (LyricLine(time=max(0.0, line.time - offset), text=line.text) for line in lines),
        key=lambda line: line.time,
    )


def _strip_title(title: str) -> str:
    """The title without what LRCLIB's entry is unlikely to have.

    **Only what names the same recording.** `live`, `remix`, `version` and `instrumental` stay, since
    those are different recordings with different lyrics or timing.
    """
    stripped = unicodedata.normalize("NFC", title).strip()
    stripped = _FEATURING_GROUP.sub("", stripped)
    stripped = _FEATURING_TAIL.sub("", stripped)
    stripped = _REMASTER_GROUP.sub("", stripped)
    stripped = _REMASTER_TAIL.sub("", stripped)
    return _TRACK_NUMBER.sub("", stripped).strip() or title.strip()


def _strip_artist(artist: str) -> str:
    """`Cardigans, The` -> `The Cardigans`, and without a featured artist."""
    stripped = _ARTIST_FEATURING.split(unicodedata.normalize("NFC", artist).strip())[0].strip()
    moved = _ARTICLE_LAST.match(stripped)
    return f"{moved.group(2)} {moved.group(1)}" if moved else stripped or artist.strip()


def _primary_artist(artist: str) -> str:
    return _ARTIST_JOIN.split(_strip_artist(artist))[0].strip()


def _without_timing(candidate: dict[str, Any]) -> dict[str, Any]:
    """The same entry as plain lyrics: its timestamps belong to a different edit."""
    plain = candidate.get("plainLyrics")
    if not plain and candidate.get("syncedLyrics"):
        plain = "\n".join(line.text for line in parse_lrc(candidate["syncedLyrics"]))
    return {**candidate, "syncedLyrics": None, "plainLyrics": plain}


def _key(text: str) -> str:
    """For comparing two spellings: no case, accents, punctuation or leading article."""
    decomposed = unicodedata.normalize("NFKD", text).casefold()
    bare = "".join(c for c in decomposed if not unicodedata.combining(c))
    words = _NON_WORD.sub(" ", bare).split()
    if len(words) > 1 and words[0] == "the":
        words = words[1:]
    return " ".join(words)


class LyricsService:
    """Finds lyrics on LRCLIB, and says whether it got an answer (ADR-0163)."""

    BASE_URL = "https://lrclib.net/api"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None,
                 min_interval: float = MIN_INTERVAL_SECONDS) -> None:
        self.client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(6.0, connect=3.0),
            headers={"User-Agent": USER_AGENT, "Lrclib-App-Id": LRCLIB_APP_ID},
        )
        self._min_interval = min_interval
        self._pace = asyncio.Lock()
        self._last_sent = 0.0
        self._hold_until = 0.0

    async def search(
        self,
        track_name: str,
        artist_name: str,
        album_name: str | None = None,
        duration: float | None = None,
        album_artist: str | None = None,
    ) -> LyricsResult | None:
        """The lyrics, or None for anything else. `resolve` says which anything else."""
        outcome = await self.resolve(track_name, artist_name, album_name, duration, album_artist)
        return outcome.result

    async def resolve(
        self,
        track_name: str,
        artist_name: str,
        album_name: str | None = None,
        duration: float | None = None,
        album_artist: str | None = None,
    ) -> LyricsOutcome:
        """Walk the ladder until something definite comes back (ADR-0163 point 2).

        **A failure ends the walk.** Carrying on after a 429 is what the rate limit forbids, and a miss
        from the remaining steps would be reported about a track nobody really asked about. A plain
        result in hand still stands, since that is an answer.
        """
        if time.monotonic() < self._hold_until:
            return LyricsOutcome(LyricsStatus.UNAVAILABLE)

        plain: LyricsResult | None = None
        for params in self._get_steps(track_name, artist_name, album_name, duration, album_artist):
            answer = await self._request("/get", params)
            if answer is _FAILED:
                return self._after_failure(plain)
            if not isinstance(answer, dict):
                continue
            if answer.get("instrumental"):
                return LyricsOutcome(LyricsStatus.INSTRUMENTAL)
            result = self._parse_response(answer)
            if result and result.synced:
                return LyricsOutcome(LyricsStatus.FOUND, result)
            if result:
                # Synced is still worth one more call, but only `/search` can offer anything new.
                plain = result
                break

        candidates = await self._request(
            "/search",
            {
                "track_name": _strip_title(track_name),
                "artist_name": _primary_artist(artist_name),
            },
        )
        if candidates is _FAILED:
            return self._after_failure(plain)

        best = self._best_candidate(
            candidates if isinstance(candidates, list) else [], track_name, artist_name, duration
        )
        if best is not None:
            if best.get("instrumental"):
                return plain_outcome(plain) if plain else LyricsOutcome(LyricsStatus.INSTRUMENTAL)
            result = self._parse_response(best)
            if result and (result.synced or plain is None):
                return plain_outcome(result)
        return plain_outcome(plain) if plain else LyricsOutcome(LyricsStatus.NOT_FOUND)

    @staticmethod
    def _get_steps(
        title: str,
        artist: str,
        album: str | None,
        duration: float | None,
        album_artist: str | None,
    ) -> list[dict[str, str | int]]:
        """Up to three `/get`s, none repeated. Album goes after the first: duration discriminates."""
        # LRCLIB takes 1-3600 only, and its own match allows two seconds either way.
        length = round(duration) if duration and 1 <= duration <= 3600 else None

        def step(track: str, by: str, on: str | None = None) -> dict[str, str | int]:
            params: dict[str, str | int] = {"track_name": track, "artist_name": by}
            if on:
                params["album_name"] = on
            if length:
                params["duration"] = length
            return params

        clean_title = _strip_title(title)
        other_artist = (
            album_artist
            if album_artist and _key(album_artist) not in (_key(artist), "various artists")
            else _primary_artist(artist)
        )
        steps = [
            step(title, artist, album),
            step(clean_title, _strip_artist(artist)),
            step(clean_title, other_artist),
        ]
        unique: list[dict[str, str | int]] = []
        for candidate in steps:
            if candidate not in unique:
                unique.append(candidate)
        return unique

    @staticmethod
    def _best_candidate(
        candidates: list[Any], title: str, artist: str, duration: float | None
    ) -> dict[str, Any] | None:
        """The acceptable `/search` result, if there is one. Never just the first (point 3).

        **A length that disagrees rules out the timing, not the words.** Right title and right artist
        at the wrong length is usually a different edit of the same song: its lyrics still apply, and
        its timestamps do not. So it comes back without them. Audited on a real library: `MillionYoung`
        "Weak Ends" at 8 s out and `Zoot Woman` "Nobody Knows" at 30 s out are both the right song.
        """
        wanted_title = _key(_strip_title(title))
        wanted_artist = _key(_strip_artist(artist))
        wanted_primary = _key(_primary_artist(artist))
        accepted: list[tuple[int, float, dict[str, Any]]] = []

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            their_artist = _key(_strip_artist(str(candidate.get("artistName") or "")))
            if their_artist not in (wanted_artist, wanted_primary) and (
                not their_artist or wanted_primary not in their_artist
            ):
                continue

            their_length = candidate.get("duration")
            distance = abs(their_length - duration) if their_length and duration else 0.0
            their_title = _strip_title(str(candidate.get("trackName") or ""))
            # `Прогноз (Prognoz, Forecast)`: a gloss on the title, only believed at a matching length.
            if _key(their_title) != wanted_title and (
                not (their_length and duration)
                or distance > GLOSSED_TITLE_DURATION_TOLERANCE
                or _key(_PARENTHETICAL.sub("", their_title)) != wanted_title
            ):
                continue

            if distance > SEARCH_DURATION_TOLERANCE:
                if not candidate.get("instrumental"):
                    accepted.append((2, distance, _without_timing(candidate)))
                continue
            accepted.append((0 if candidate.get("syncedLyrics") else 1, distance, candidate))

        return min(accepted, key=lambda item: item[:2])[2] if accepted else None

    async def _request(self, path: str, params: dict[str, str | int]) -> Any:
        """The decoded body, None for a definite "no", or `_FAILED` for no answer at all."""
        async with self._pace:
            wait = self._last_sent + self._min_interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_sent = time.monotonic()

        try:
            response = await self.client.get(f"{self.BASE_URL}{path}", params=params)
        except httpx.TransportError as exc:
            logger.warning("LRCLIB %s failed: %s", path, type(exc).__name__)
            return _FAILED

        if response.status_code == 429 or response.status_code >= 500:
            hold = _retry_after(response.headers.get("retry-after"))
            if response.status_code == 429 or hold:
                self._hold_until = time.monotonic() + (hold or DEFAULT_HOLD_SECONDS)
            logger.warning("LRCLIB %s answered %s", path, response.status_code)
            return _FAILED
        if response.status_code != 200:
            return None
        try:
            return response.json()
        except ValueError:
            logger.warning("LRCLIB %s answered 200 with a body that is not JSON", path)
            return _FAILED

    @staticmethod
    def _after_failure(plain: LyricsResult | None) -> LyricsOutcome:
        return plain_outcome(plain) if plain else LyricsOutcome(LyricsStatus.UNAVAILABLE)

    def _parse_response(self, data: dict[str, Any]) -> LyricsResult | None:
        """Parse LRCLIB response into LyricsResult."""
        synced_lyrics: str | None = data.get("syncedLyrics")
        plain_lyrics: str | None = data.get("plainLyrics")
        source_id = f"lrclib:{data['id']}" if data.get("id") is not None else None

        if synced_lyrics:
            lines = parse_lrc(synced_lyrics)
            if lines:
                return LyricsResult(
                    synced=True,
                    lines=lines,
                    plain_text=plain_lyrics or "\n".join(line.text for line in lines),
                    source="lrclib",
                    source_id=source_id,
                )

        if not plain_lyrics:
            return None
        return LyricsResult(
            synced=False,
            lines=[LyricLine(time=0.0, text=line) for line in plain_lyrics.split("\n") if line.strip()],
            plain_text=plain_lyrics,
            source="lrclib",
            source_id=source_id,
        )

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()


# Singleton instance
_lyrics_service: LyricsService | None = None


def get_lyrics_service() -> LyricsService:  # type: ignore[return]
    """Get or create the lyrics service singleton."""
    global _lyrics_service
    if _lyrics_service is None:
        _lyrics_service = LyricsService()
    return _lyrics_service
