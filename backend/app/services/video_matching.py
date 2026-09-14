"""Decide, without a person, whether a YouTube search result is a track's music video.

The match sheet in the Mac app puts five results in front of someone and lets them choose; this is
the same judgement written down, for a batch that nobody wants to sit through. It is deliberately
**strict**: the cost of a wrong video is a wrong video on the shelf forever, and the cost of a
missed one is a track that can still be matched by hand — so every rule here errs towards "no".

What a match requires, all at once:

1. **The artist is named** — every token of the primary artist appears in the result's title, or
   the artist's name runs through the channel (`InterpolVEVO`, `The Cure - Topic`).
2. **The title is named** — every token of the track's title, after its parenthetical noise
   (``(2011 Remaster)``, ``[feat. X]``), appears in the result's title.
3. **It is the right length** — within 20% or 30 seconds of the track, whichever is more generous,
   because a video has an intro and an outro and an album cut does not. A full album, a live set
   or a ten-minute extended mix fails this before anything reads its title.
4. **Nothing in the result says it is not the video** — live, cover, lyric video, official audio,
   remix, reaction, karaoke and the rest. A word the *track's own title* carries is exempt: a
   song called "Remix" may match a result called "Remix".
5. **It is not an art track.** YouTube generates an upload for every track a label delivers —
   the album cover, the audio, the bare title, on the artist's own channel, exactly the album
   length. They pass every rule above and are not videos. Their description opens "Provided to
   YouTube by", which is the tell; a channel ending "- Topic" is the older form of the same thing.
6. **Somebody credible uploaded it** — the title says official video, or the channel is the
   artist's or a VEVO/official one. A bare "Song - Artist" from a stranger's channel is a
   re-upload of the audio with a picture more often than it is the video.
7. **Every bracket is accounted for.** "(Official Video)", "(HD)", "(2012 Remaster)", "(feat. X)"
   say things the rules understand. "(Pepsi Smash on Yahoo! Music 2007)", "(Fan Submission)",
   "(alternate)" say the upload is *something else* — and they came from the artist's own
   channel, which passed every rule above. A bracket the rules cannot explain is a reason to
   refuse, because the list of things it might be is the list of things this must not fetch.

Among results that pass, "official video" in the title and an official-looking channel rank first,
then the closest duration. A result that passes nothing is reported with the first rule it broke,
so the person who reads the log can see whether the rule or the search was wrong.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.services.video import VideoSearchResult

# Phrases whose presence in a result title says "not the music video". Matched as whole-token
# sequences on normalised text, so "livestream" is not "live" but "live at" is.
REJECT_PHRASES: tuple[tuple[str, ...], ...] = tuple(
    tuple(p.split())
    for p in (
        "live", "cover", "covers", "karaoke", "lyric video", "lyrics video", "lyrics", "lyric",
        "official audio", "audio only", "audio", "full album", "reaction", "reacts", "instrumental",
        "performance", "session", "sessions", "rehearsal", "soundcheck",
        "acoustic version", "acoustic", "slowed", "sped up", "nightcore", "8d", "remix", "mashup",
        "parody", "tutorial", "lesson", "visualizer", "visualiser", "teaser", "trailer",
        "behind the scenes", "making of", "interview", "extended mix", "extended version",
        "dj set", "mix", "megamix", "medley", "fan made", "fanmade", "unofficial",
    )
)

# Words that say "official video" — the positive signal: credibility from a stranger's channel,
# ranking, and the whole case when the track's own duration is unknown. "Music video" on its own
# is not here: a fan-made video says that too, and did in the dry run.
OFFICIAL_PHRASES: tuple[tuple[str, ...], ...] = tuple(
    tuple(p.split())
    for p in ("official video", "official music video", "official hd video", "official 4k video")
)

# Parenthetical noise stripped from a track title before its tokens are required.
_NOISE_SEGMENT = re.compile(
    r"\s*[\(\[][^\)\]]*"
    r"(remaster|remastered|version|edit|mix|feat\.?|featuring|mono|stereo|deluxe|bonus|explicit|"
    r"clean|single|album|radio|live|demo|\d{4})"
    r"[^\)\]]*[\)\]]",
    re.IGNORECASE,
)
_TRAILING_NOISE = re.compile(
    r"\s*-\s*(\d{4}\s+)?(remaster(ed)?|single version|album version|radio edit)(\s+\d{4})?\s*$",
    re.IGNORECASE,
)
# Only the guest separators. "&" and "and" are not split on: "Simon & Garfunkel" and "Belle and
# Sebastian" are one name, and requiring only its first half would let "Simon" match anything.
_ARTIST_SPLIT = re.compile(r"\s+(feat\.?|featuring|ft\.?|vs\.?)\s+|,\s*", re.IGNORECASE)


# Letters NFKD leaves whole and the ASCII step would then drop. "Ágætis Byrjun" must survive as
# "agaetis byrjun", which is how YouTube spells it.
_LETTER_FOLDS = str.maketrans({
    "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE", "ø": "o", "Ø": "O", "ß": "ss",
    "ð": "d", "Ð": "D", "þ": "th", "Þ": "TH", "ł": "l", "Ł": "L", "đ": "d", "Đ": "D",
})


def normalise(text: str | None) -> str:
    """Lowercase ASCII words separated by single spaces; accents folded, punctuation gone."""
    folded = unicodedata.normalize("NFKD", (text or "").translate(_LETTER_FOLDS)).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", folded.lower()).split())


def tokens(text: str) -> list[str]:
    return normalise(text).split()


def _significant(words: list[str]) -> list[str]:
    """Tokens worth requiring: single letters ("s" from "he's") prove nothing."""
    return [w for w in words if len(w) > 1 or w.isdigit()]


def title_tokens(title: str) -> list[str]:
    """The track title's tokens with its parenthetical noise removed — unless that is all of it."""
    stripped = _TRAILING_NOISE.sub("", _NOISE_SEGMENT.sub("", title)).strip()
    words = _significant(tokens(stripped or title))
    return words or _significant(tokens(title))


def primary_artist(artist: str) -> str:
    """The name before any "feat." or "," — the one the video is filed under."""
    head = _ARTIST_SPLIT.split(artist, maxsplit=1)[0].strip()
    return head or artist


def artist_tokens(artist: str) -> list[str]:
    words = _significant(tokens(primary_artist(artist)))
    if len(words) > 1 and words[0] == "the":
        words = words[1:]
    return words


def _contains_phrase(haystack: list[str], phrase: tuple[str, ...]) -> bool:
    n = len(phrase)
    return any(tuple(haystack[i : i + n]) == phrase for i in range(len(haystack) - n + 1))


def _names_artist(artist: str, result: VideoSearchResult) -> bool:
    wanted = artist_tokens(artist)
    if not wanted:
        return False
    in_title = tokens(result.title)
    if all(w in in_title for w in wanted):
        return True
    # "InterpolVEVO", "thecureofficial": the channel is the artist. Naming is looser than
    # credibility — a "- Topic" channel names the artist too, and is refused later for what it is.
    channel = normalise(result.channel).replace(" ", "")
    is_topic = channel.startswith("".join(wanted)) and channel.endswith("topic")
    return _artist_channel(artist, result) or is_topic


def _names_title(title: str, result: VideoSearchResult) -> bool:
    wanted = title_tokens(title)
    in_title = tokens(result.title)
    return bool(wanted) and all(w in in_title for w in wanted)


def duration_tolerance(track_seconds: float) -> float:
    return max(30.0, track_seconds * 0.2)


def _rejecting_phrase(track_title: str, result: VideoSearchResult) -> str | None:
    exempt = set(tokens(track_title))
    words = tokens(result.title)
    for phrase in REJECT_PHRASES:
        if all(w in exempt for w in phrase):
            continue
        if _contains_phrase(words, phrase):
            return " ".join(phrase)
    return None


# Words a bracketed segment may contain and still be the video. Anything else in a bracket is
# the upload telling you what it is instead.
EXPLAINED_BRACKET_WORDS = frozenset(
    "official video music hd hq 4k 1080p 720p remaster remastered version edit feat ft featuring "
    "explicit clean uncensored single album radio directors director cut full length stereo mono "
    "widescreen restored upscaled upgrade new".split()
)
_BRACKET = re.compile(r"[\(\[][^\)\]]*[\)\]]")


def _unexplained_bracket(track_title: str, artist: str, result: VideoSearchResult) -> str | None:
    known = EXPLAINED_BRACKET_WORDS | set(tokens(track_title)) | set(tokens(artist))
    for segment in _BRACKET.findall(result.title):
        words = [w for w in tokens(segment) if not w.isdigit()]
        # A guest credit names somebody the track's own title may not: the bracket is explained
        # by its first word.
        if words and words[0] in ("feat", "ft", "featuring", "with"):
            continue
        if any(w not in known for w in words):
            return segment
    return None


def _looks_official(result: VideoSearchResult) -> bool:
    words = tokens(result.title)
    return any(_contains_phrase(words, p) for p in OFFICIAL_PHRASES)


def _official_channel(artist: str, result: VideoSearchResult) -> bool:
    """VEVO, or "official" *with the artist's name* — `MusicStationOfficial` is a re-upload
    channel that the word alone let through."""
    channel = normalise(result.channel).replace(" ", "")
    if "vevo" in channel:
        return True
    return "official" in channel and _artist_channel(artist, result)


# What an artist's own channel may add to the name: "InterpolVEVO", "pinbackmusic", "The Cure
# Official". Not an open substring test — "Modest Mouse Man" contains the name and is a fan.
CHANNEL_SUFFIXES = ("", "vevo", "official", "music", "tv", "band", "records", "videos", "hq", "channel")


def _artist_channel(artist: str, result: VideoSearchResult) -> bool:
    """The channel *is* the artist: the name, with at most a conventional suffix."""
    wanted = "".join(artist_tokens(artist))
    if not wanted:
        return False
    channel = normalise(result.channel).replace(" ", "")
    if channel.startswith("the") and not wanted.startswith("the"):
        channel = channel[3:]
    return any(channel == wanted + suffix for suffix in CHANNEL_SUFFIXES)


def is_art_track(result: VideoSearchResult) -> bool:
    """YouTube's auto-generated audio upload, which is the song but not a video of it."""
    if normalise(result.description).startswith("provided to youtube by"):
        return True
    return normalise(result.channel).endswith(" topic")


def _credible(artist: str, result: VideoSearchResult) -> bool:
    return _looks_official(result) or _artist_channel(artist, result) or _official_channel(artist, result)


@dataclass(frozen=True)
class Verdict:
    """What the chooser decided, and in words a log reader can act on."""

    result: VideoSearchResult | None
    reason: str

    @property
    def matched(self) -> bool:
        return self.result is not None


def choose(
    *,
    title: str,
    artist: str,
    duration_seconds: float | None,
    results: list[VideoSearchResult],
) -> Verdict:
    """The one result that is confidently this track's video, or why none is."""
    if not results:
        return Verdict(None, "no results")

    passing: list[tuple[tuple[int, int, float], VideoSearchResult, str]] = []
    first_failure: str | None = None

    def fail(why: str) -> None:
        nonlocal first_failure
        if first_failure is None:
            first_failure = why

    for result in results:
        if not _names_artist(artist, result):
            fail(f"does not name the artist: {result.title!r} ({result.channel})")
            continue
        if not _names_title(title, result):
            fail(f"does not name the title: {result.title!r}")
            continue
        phrase = _rejecting_phrase(title, result)
        if phrase:
            fail(f"says {phrase!r}: {result.title!r}")
            continue
        if is_art_track(result):
            fail(f"is an art track (audio with the cover): {result.title!r} ({result.channel})")
            continue
        if not _credible(artist, result):
            fail(f"not called official and not the artist's channel: {result.title!r} ({result.channel})")
            continue
        bracket = _unexplained_bracket(title, artist, result)
        if bracket:
            fail(f"bracket says it is something else {bracket!r}: {result.title!r}")
            continue
        if duration_seconds:
            off = abs(result.duration - duration_seconds)
            tolerance = duration_tolerance(duration_seconds)
            if off > tolerance:
                fail(f"{off:.0f}s off ({result.duration}s vs {duration_seconds:.0f}s): {result.title!r}")
                continue
        else:
            # Nothing to check the length against, so the title has to say it is the video.
            if not _looks_official(result):
                fail(f"no track duration and not called an official video: {result.title!r}")
                continue
            off = 0.0
        rank = (int(_looks_official(result)), int(_official_channel(artist, result)), -off)
        note = f"{'official video' if rank[0] else 'named'}, {off:.0f}s off, {result.channel}"
        passing.append((rank, result, note))

    if not passing:
        return Verdict(None, first_failure or "no result passed")

    passing.sort(key=lambda item: item[0], reverse=True)
    rank, best, note = passing[0]
    return Verdict(best, f"matched: {note}")
