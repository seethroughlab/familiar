"""Lyrics fetching service using LRCLIB.net for synced lyrics."""

import re
from dataclasses import dataclass
from typing import Any

import httpx


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


class LyricsService:
    """Service for fetching song lyrics with optional sync timing."""

    BASE_URL = "https://lrclib.net/api"

    def __init__(self) -> None:
        self.client = httpx.AsyncClient(
            timeout=10.0,
            headers={"User-Agent": "Familiar/1.0"}
        )

    async def search(
        self,
        track_name: str,
        artist_name: str,
        album_name: str | None = None,
        duration: float | None = None
    ) -> LyricsResult | None:
        """
        Search for lyrics by track metadata.
        Returns synced lyrics if available, otherwise plain lyrics.
        """
        # Try the get endpoint first (more precise with duration)
        if duration:
            result = await self._get_by_metadata(
                track_name, artist_name, album_name, duration
            )
            if result:
                return result

        # Fall back to search endpoint
        return await self._search_lyrics(track_name, artist_name)

    async def _get_by_metadata(
        self,
        track_name: str,
        artist_name: str,
        album_name: str | None,
        duration: float
    ) -> LyricsResult | None:
        """Get lyrics using precise metadata matching."""
        try:
            params: dict[str, str | int] = {
                "track_name": track_name,
                "artist_name": artist_name,
                "duration": int(duration)
            }
            if album_name:
                params["album_name"] = album_name

            response = await self.client.get(
                f"{self.BASE_URL}/get",
                params=params  # type: ignore[arg-type]
            )

            if response.status_code == 200:
                data: dict[str, Any] = response.json()
                return self._parse_response(data)

            return None
        except Exception:
            return None

    async def _search_lyrics(
        self,
        track_name: str,
        artist_name: str
    ) -> LyricsResult | None:
        """Search for lyrics by track and artist name."""
        try:
            response = await self.client.get(
                f"{self.BASE_URL}/search",
                params={
                    "track_name": track_name,
                    "artist_name": artist_name
                }
            )

            if response.status_code == 200:
                data: list[Any] | dict[str, Any] = response.json()
                if isinstance(data, list) and len(data) > 0:
                    # Return first result
                    return self._parse_response(data[0])

            return None
        except Exception:
            return None

    def _parse_response(self, data: dict[str, Any]) -> LyricsResult | None:
        """Parse LRCLIB response into LyricsResult."""
        synced_lyrics: str | None = data.get("syncedLyrics")
        plain_lyrics: str | None = data.get("plainLyrics")

        if not synced_lyrics and not plain_lyrics:
            return None

        if synced_lyrics:
            lines = parse_lrc(synced_lyrics)
            return LyricsResult(
                synced=True,
                lines=lines,
                plain_text=plain_lyrics or "\n".join(line.text for line in lines),
                source="lrclib"
            )
        else:
            # Plain lyrics only - we know plain_lyrics is not None at this point
            assert plain_lyrics is not None  # mypy narrowing
            plain_text = plain_lyrics
            lines = [
                LyricLine(time=0.0, text=line)
                for line in plain_text.split("\n")
                if line.strip()
            ]
            return LyricsResult(
                synced=False,
                lines=lines,
                plain_text=plain_text,
                source="lrclib"
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
