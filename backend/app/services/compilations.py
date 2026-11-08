"""Which tracks make up a compilation (ADR-0167).

A compilation is one record, not a shared title. The rule this replaced labelled any album
title held by more than one artist, anywhere in the library, "Various Artists". So Portishead's
*Third* became a compilation because Soft Machine also has a *Third*, and through the album
key both records became one album with one cover.

The evidence that a shared title is one record:

1. **One folder** holding more than one artist under the title.
2. **Several folders** whose disc and track numbers never repeat between artists. A
   compilation stored one artist per folder (*Parts in the Post* across 17 folders)
   interleaves into one sequence. Two albums that share a title each start at track 1.
3. When numbers do repeat across folders, an artist with ``OWN_ALBUM_MIN_TRACKS`` or more
   tracks under the title is their own album and is left out. The rest is still one
   compilation (*The Wire 20 Years*: 40 artists, one track each, with no disc numbers).

Pure, so the cases that went wrong can be pinned without a database.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Hashable, Iterable
from dataclasses import dataclass

#: What a compilation's album artist is set to.
VARIOUS_ARTISTS = "Various Artists"

#: An artist holding this many tracks of their own under a title whose numbers collide is
#: taken to have their own album of that name (ADR-0167 point 2).
OWN_ALBUM_MIN_TRACKS = 3

_FEATURING = re.compile(r"\s+(feat\.?|ft\.?|featuring)\s+.*$", re.IGNORECASE)


def artist_key(artist: str | None) -> str:
    """The artist as the rule compares it: "feat." credits stripped, case folded.

    The stripping is what kept "Massive Attack feat. Damon Albarn" from making *Heligoland*
    a compilation under the old rule, and it carries over unchanged.
    """
    return _FEATURING.sub("", (artist or "").strip()).strip().lower()


def title_key(album: str | None) -> str:
    return (album or "").strip().lower()


@dataclass(frozen=True)
class CompilationEvidence:
    """One track, as the rule sees it."""

    id: Hashable
    album: str
    artist: str
    folder: str
    disc_number: int | None = None
    track_number: int | None = None


def _numbers_repeat_between_artists(tracks: list[CompilationEvidence]) -> bool:
    owners: dict[tuple[int, int], set[str]] = defaultdict(set)
    for t in tracks:
        if t.track_number is None:
            continue
        owners[(t.disc_number or 1, t.track_number)].add(artist_key(t.artist))
    return any(len(artists) > 1 for artists in owners.values())


def _is_shared(tracks: list[CompilationEvidence]) -> bool:
    """More than one artist, and no artist with more than half the tracks."""
    counts: dict[str, int] = defaultdict(int)
    for t in tracks:
        counts[artist_key(t.artist)] += 1
    return len(counts) > 1 and max(counts.values()) * 2 <= len(tracks)


def _judge_title(tracks: list[CompilationEvidence]) -> set[Hashable]:
    """The ids of one title's tracks that belong to a compilation."""
    labelled: set[Hashable] = set()

    by_folder: dict[str, list[CompilationEvidence]] = defaultdict(list)
    for t in tracks:
        by_folder[t.folder].append(t)

    # 1. One folder, several artists, none of them holding most of it. An album with a
    #    guest-credited track ("Plaid & Björk" on Plaid's *Not for Threes*) is still its
    #    artist's album.
    for in_folder in by_folder.values():
        if _is_shared(in_folder):
            labelled.update(t.id for t in in_folder)

    if len(by_folder) < 2:
        return labelled

    # 2. Several folders: one sequence, unless artists repeat each other's numbers.
    candidates = tracks
    if _numbers_repeat_between_artists(tracks):
        # 3. Artists with a run of their own are their own album.
        counts: dict[str, int] = defaultdict(int)
        for t in tracks:
            counts[artist_key(t.artist)] += 1
        candidates = [t for t in tracks if counts[artist_key(t.artist)] < OWN_ALBUM_MIN_TRACKS]

    if _is_shared(candidates):
        labelled.update(t.id for t in candidates)

    return labelled


def compilation_track_ids(tracks: Iterable[CompilationEvidence]) -> set[Hashable]:
    """The ids, among ``tracks``, of every track that belongs to a compilation.

    Pass every track that could be part of one: the caller decides which tracks are
    evidence (blank or "Various Artists" album artist) and which it may write to.
    """
    by_title: dict[str, list[CompilationEvidence]] = defaultdict(list)
    for t in tracks:
        key = title_key(t.album)
        if key:
            by_title[key].append(t)

    labelled: set[Hashable] = set()
    for title_tracks in by_title.values():
        if len({artist_key(t.artist) for t in title_tracks}) > 1:
            labelled |= _judge_title(title_tracks)
    return labelled
