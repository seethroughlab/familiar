"""Which MusicBrainz recording an AcoustID answer names — or none (ADR-0115 point 3).

Pure. Takes the JSON AcoustID returns for ``meta=recordings releasegroups sources``
and what the library knows about the track, and decides in four tiers. Every
tier is the first rule that leaves *exactly one* recording; anything else is a
refusal that keeps its candidates. Nothing here guesses: no stemming, no
transliteration, no "close enough" beyond token overlap, because a wrong id is a
claim the corpus counts and a key deduplication trusts, and the measurement in
the ADR shows what "first candidate" would have named.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

#: The top AcoustID result must score at least this to be considered at all.
MIN_SCORE = 0.8

#: Token-set overlap (Jaccard) at or above this is a title or album match. In
#: practice it means identical after lower-casing and dropping punctuation, or one
#: token in five different — "Sambatiki (2004 Remaster)" against "Sambatiki 2004
#: Remaster" matches, "Fenixfunk 5" against "Fenix Funk 5" does not. The second is
#: the case the ADR chose to leave for a person rather than a looser rule, and the
#: 9% / 3.5% split in its measurement was taken at exactly this value.
MATCH_THRESHOLD = 0.8

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def tokens(text: str | None) -> set[str]:
    """Lower-cased alphanumeric tokens; punctuation and spacing carry no meaning."""
    return set(_NON_ALNUM.sub(" ", (text or "").lower()).split())


def similarity(a: str | None, b: str | None) -> float:
    """Jaccard overlap of the two token sets. 0.0 when either is empty."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


@dataclass(frozen=True)
class Candidate:
    """One recording AcoustID offered, flattened to what the tiers read."""

    recording_mbid: str
    title: str | None
    artist: str | None
    release_groups: tuple[str, ...]
    sources: int


@dataclass(frozen=True)
class Resolution:
    """The decision, and enough to see why it was made."""

    #: The id to write and claim, or None for a refusal.
    recording_mbid: str | None
    #: 1–4 when resolved; None otherwise.
    tier: int | None
    #: The top result's score, or 0.0 when AcoustID returned nothing.
    score: float
    #: One word for the refusal or the tier — what `acoustid_lookup` records.
    reason: str
    #: Every recording at the top result, so a refusal can be revisited offline.
    candidates: tuple[Candidate, ...] = field(default_factory=tuple)

    @property
    def resolved(self) -> bool:
        return self.recording_mbid is not None


def _candidates(result: dict[str, Any]) -> tuple[Candidate, ...]:
    out: list[Candidate] = []
    seen: set[str] = set()
    for rec in result.get("recordings") or []:
        mbid = str(rec.get("id") or "").lower()
        if not mbid or mbid in seen:
            continue
        seen.add(mbid)
        artists = [a.get("name") for a in (rec.get("artists") or []) if a.get("name")]
        out.append(
            Candidate(
                recording_mbid=mbid,
                title=rec.get("title"),
                artist="; ".join(artists) or None,
                release_groups=tuple(
                    g.get("title") or "" for g in (rec.get("releasegroups") or [])
                ),
                sources=int(rec.get("sources") or 0),
            )
        )
    return tuple(out)


def resolve(
    response: dict[str, Any],
    *,
    title: str | None,
    album: str | None,
) -> Resolution:
    """Decide from an AcoustID lookup response and the track's own title and album.

    The tiers, in the order the ADR fixes them:

    1. the top result lists one recording;
    2. exactly one recording's title matches the track's;
    3. among the title matches, exactly one has a release group matching the album;
    4. among what tier 2 or 3 left, one recording has strictly more ``sources``.

    Tier 4 runs whether tier 3 left several or none — "several title matches, no
    album match" is the 5% bucket the measurement found, and the popular duplicate
    is the same answer there as anywhere. A tie refuses.
    """
    results = response.get("results") or []
    if not results:
        return Resolution(None, None, 0.0, "no_result")

    top = max(results, key=lambda r: float(r.get("score") or 0.0))
    score = float(top.get("score") or 0.0)
    candidates = _candidates(top)

    if score < MIN_SCORE:
        return Resolution(None, None, score, "low_score", candidates)
    if not candidates:
        return Resolution(None, None, score, "no_recording", candidates)
    if len(candidates) == 1:
        return Resolution(candidates[0].recording_mbid, 1, score, "single", candidates)

    by_title = [c for c in candidates if similarity(c.title, title) >= MATCH_THRESHOLD]
    if len(by_title) == 1:
        return Resolution(by_title[0].recording_mbid, 2, score, "title", candidates)
    if not by_title:
        return Resolution(None, None, score, "no_title_match", candidates)

    by_album = [
        c
        for c in by_title
        if any(similarity(g, album) >= MATCH_THRESHOLD for g in c.release_groups)
    ]
    if len(by_album) == 1:
        return Resolution(by_album[0].recording_mbid, 3, score, "release_group", candidates)

    pool = by_album or by_title
    ranked = sorted(pool, key=lambda c: c.sources, reverse=True)
    if len(ranked) >= 2 and ranked[0].sources > ranked[1].sources:
        return Resolution(ranked[0].recording_mbid, 4, score, "sources", candidates)
    return Resolution(None, None, score, "tied", candidates)


def candidates_as_json(resolution: Resolution) -> list[dict[str, Any]]:
    """The shape stored in ``acoustid_lookup.candidates``. A superset of what the
    identification feature writes — ``acoustid_score``, ``musicbrainz_recording_id``,
    ``title``, ``artist`` — so its reader keeps working on rows this job wrote."""
    return [
        {
            "acoustid_score": resolution.score,
            "musicbrainz_recording_id": c.recording_mbid,
            "title": c.title,
            "artist": c.artist,
            "release_groups": list(c.release_groups),
            "sources": c.sources,
        }
        for c in resolution.candidates
    ]
