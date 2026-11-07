"""Lyrics the listener already has: a hand edit, a `.lrc` beside the file, or the file's own tags.

ADR-0163 point 1. Everything here reads and nothing writes, so zero-touch is unaffected, and it runs
at lookup time, so no library re-scan is needed for it to work. The tag reader has always found
embedded lyrics (`metadata/reader.py`); the scanner kept only their language and dropped the text,
which is why `Track.lyrics` was empty on every row of a 27,366-track library.

Called from a worker thread: mutagen and the filesystem both block.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from app.services.lyrics import LyricLine, LyricsResult, parse_lrc

logger = logging.getLogger(__name__)

#: ID3 SYLT's timestamp format 2 means milliseconds. Format 1 counts MPEG frames, which would need
#: the file's frame rate to mean anything, so it is not read.
_SYLT_MILLISECONDS = 2


@dataclass
class LocalLyrics:
    """What the listener's own copy offers, before anything is asked of LRCLIB."""

    synced: LyricsResult | None = None
    plain: LyricsResult | None = None


def sidecar_path(audio_path: Path) -> Path | None:
    """`song.flac` -> `song.lrc`, in either case, if one is there."""
    for suffix in (".lrc", ".LRC"):
        candidate = audio_path.with_suffix(suffix)
        if candidate.is_file():
            return candidate
    return None


def read_local_lyrics(file_path: str | None, edited: str | None) -> LocalLyrics:
    """The best synced and the best plain lyrics, each in ADR-0163 point 1's order.

    Synced: an edit, a sidecar, SYLT, embedded text with LRC timestamps. Plain: an edit, embedded
    text. A sidecar or a tag that cannot be read is skipped, never raised: a corrupt file must not
    cost the listener the LRCLIB lookup that comes after.
    """
    found = LocalLyrics()
    edited_result = _from_text(edited, "edited")
    _offer(found, edited_result)

    if not file_path:
        return found
    path = Path(file_path)

    sidecar = sidecar_path(path)
    if sidecar is not None:
        try:
            text = sidecar.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as exc:
            logger.info("Could not read %s: %s", sidecar.name, exc)
        else:
            result = _from_text(text, "sidecar")
            if result is not None and result.synced:
                _offer(found, result)

    if found.synced is not None and found.plain is not None:
        return found

    for result in _from_tags(path):
        _offer(found, result)
    return found


def _offer(found: LocalLyrics, result: LyricsResult | None) -> None:
    """Keep the first of each kind, since the sources arrive in rank order."""
    if result is None:
        return
    if result.synced:
        found.synced = found.synced or result
    else:
        found.plain = found.plain or result


def _from_text(text: str | None, source: str) -> LyricsResult | None:
    """LRC if it has timestamps, otherwise plain. Embedded lyrics are often LRC pasted into a tag."""
    if not text or not text.strip():
        return None
    lines = parse_lrc(text)
    if lines:
        return LyricsResult(
            synced=True,
            lines=lines,
            plain_text="\n".join(line.text for line in lines),
            source=source,
        )
    plain = text.replace("\r\n", "\n").strip()
    return LyricsResult(
        synced=False,
        lines=[LyricLine(time=0.0, text=line) for line in plain.split("\n") if line.strip()],
        plain_text=plain,
        source=source,
    )


def _from_tags(path: Path) -> list[LyricsResult]:
    """SYLT first, then any unsynchronised text, as found in ID3, Vorbis comments and MP4."""
    try:
        import mutagen

        audio = mutagen.File(path)
    except Exception as exc:  # mutagen raises a dozen types for a damaged file
        logger.info("Could not read tags from %s: %s", path.name, exc)
        return []
    tags = getattr(audio, "tags", None)
    if not tags:
        return []

    results: list[LyricsResult] = []
    texts: list[str] = []

    if hasattr(tags, "getall"):  # ID3
        for frame in tags.getall("SYLT"):
            if getattr(frame, "format", None) != _SYLT_MILLISECONDS:
                continue
            lines = sorted(
                (LyricLine(time=ms / 1000, text=str(text).strip()) for text, ms in frame.text if str(text).strip()),
                key=lambda line: line.time,
            )
            if lines:
                results.append(LyricsResult(
                    synced=True, lines=lines,
                    plain_text="\n".join(line.text for line in lines), source="embedded",
                ))
        texts.extend(str(frame.text) for frame in tags.getall("USLT"))
    else:
        for key in ("lyrics", "unsyncedlyrics", "syncedlyrics", "\xa9lyr"):
            try:
                values = tags.get(key) or tags.get(key.upper())
            except Exception:  # some tag types raise rather than return None for odd keys
                values = None
            if values:
                texts.extend(str(value) for value in (values if isinstance(values, list) else [values]))

    for text in texts:
        result = _from_text(text, "embedded")
        if result is not None:
            results.append(result)
    # Synced before plain, keeping each kind's order: SYLT, then LRC pasted into a text tag.
    return sorted(results, key=lambda result: not result.synced)
