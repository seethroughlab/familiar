"""Background auto-generation of proposed metadata changes.

Scans the library for self-contained, high-confidence metadata issues and queues
``ProposedChange`` rows (status=PENDING, source=AUTO_ENRICHMENT) for user review —
without needing the LLM or external lookups. This is what makes proposals appear
in the Proposed Changes panel/indicator on their own (previously they only
appeared when the user explicitly asked the chat to fix metadata).

v1 detects duplicate artist spellings and proposes merging each variant into the
most common spelling. The detection mirrors the LLM ``find_duplicate_artists``
tool so the two paths agree.
"""

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChangeSource, ChangeStatus, ProposedChange, Track
from app.services.compilations import (
    OWN_ALBUM_MIN_TRACKS,
    VARIOUS_ARTISTS,
    CompilationEvidence,
    artist_key,
    compilation_track_ids,
    title_key,
)
from app.services.normalize import normalize_for_matching
from app.services.proposed_changes import ProposedChangesService

logger = logging.getLogger(__name__)


def normalize_artist_for_comparison(artist: str) -> str:
    """Normalize an artist name for duplicate detection.

    Mirrors ``MetadataHandlersMixin._normalize_artist_for_comparison`` so the
    automated scan and the LLM tool detect the same duplicates.
    """
    if not artist:
        return ""
    s = artist.lower().strip()
    s = s.replace("_", " ").replace("-", " ")
    s = s.replace(" & ", " and ").replace(" + ", " and ")
    s = s.replace("&", " and ").replace("+", " and ")
    s = " ".join(s.split())
    return s


def find_duplicate_artist_groups(
    artists: list[tuple[str, int]],
) -> list[dict]:
    """Group ``(artist_name, track_count)`` tuples by normalized spelling.

    Pure function (no DB access) so it is easy to unit-test. Returns only groups
    with more than one spelling variant, each as
    ``{"canonical": <most common spelling>, "variants": [(name, count), ...]}``,
    sorted by total track count descending.
    """
    groups: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for name, count in artists:
        norm = normalize_artist_for_comparison(name)
        if norm:
            groups[norm].append((name, count))

    result: list[dict] = []
    for variants in groups.values():
        if len(variants) > 1:
            variants_sorted = sorted(variants, key=lambda x: x[1], reverse=True)
            result.append({"canonical": variants_sorted[0][0], "variants": variants_sorted})

    result.sort(key=lambda g: sum(c for _, c in g["variants"]), reverse=True)
    return result


async def scan_for_duplicate_artist_proposals(
    db: AsyncSession,
    *,
    max_groups: int = 25,
) -> int:
    """Detect duplicate artist spellings and queue merge proposals.

    Idempotent: skips any variant already covered by a pending artist-merge
    proposal, so it is safe to run after every sync. Returns the number of new
    proposals created.
    """
    # Distinct active artists with track counts.
    stmt = (
        select(Track.artist, func.count(Track.id).label("track_count"))
        .where(Track.active_filter(), Track.artist.isnot(None), Track.artist != "")
        .group_by(Track.artist)
    )
    rows = (await db.execute(stmt)).all()
    artists = [(row.artist, row.track_count) for row in rows]

    groups = find_duplicate_artist_groups(artists)[:max_groups]
    if not groups:
        return 0

    # Dedup against pending artist-merge proposals by their target-id set.
    existing_rows = (
        await db.execute(
            select(ProposedChange).where(
                ProposedChange.status == ChangeStatus.PENDING,
                ProposedChange.change_type == "metadata",
                ProposedChange.field == "artist",
            )
        )
    ).scalars().all()
    existing_targets = {frozenset(c.target_ids) for c in existing_rows}

    service = ProposedChangesService(db)
    created = 0

    for group in groups:
        canonical = group["canonical"]
        for variant_name, _count in group["variants"]:
            if variant_name == canonical:
                continue

            track_id_rows = (
                await db.execute(
                    select(Track.id).where(
                        Track.active_filter(),
                        Track.artist == variant_name,
                    )
                )
            ).all()
            track_ids = [str(tid) for (tid,) in track_id_rows]
            if not track_ids:
                continue

            key = frozenset(track_ids)
            if key in existing_targets:
                continue

            await service.create_change(
                change_type="metadata",
                target_type="track",
                target_ids=track_ids,
                source=ChangeSource.AUTO_ENRICHMENT,
                new_value=canonical,
                field="artist",
                old_value=variant_name,
                confidence=0.9,
                reason=(
                    f"'{variant_name}' looks like a spelling variant of '{canonical}' "
                    f"(auto-detected). Merging unifies {len(track_ids)} track(s)."
                ),
            )
            existing_targets.add(key)
            created += 1

    if created:
        logger.info(f"Auto-proposals: created {created} duplicate-artist merge proposal(s)")
    return created


async def run_auto_proposal_scan() -> int:
    """Background entry point: owns its engine/session and returns count created."""
    from app.db.session import create_task_engine_session

    engine, session_maker = create_task_engine_session()
    try:
        async with session_maker() as db:
            created = await scan_for_duplicate_artist_proposals(db)
            created += await scan_for_album_move_proposals(db, include_splits=False)
            return created
    finally:
        await engine.dispose()


# ── ADR-0166: tracks on the wrong album ─────────────────────────────────────────


@dataclass(frozen=True)
class AlbumTrackRow:
    """One active, titled track, as the album-move rules see it."""

    id: str
    album: str
    artist: str
    album_artist: str
    folder: str
    disc_number: int | None
    track_number: int | None
    album_id: str | None
    album_has_release_id: bool = False


@dataclass
class AlbumMovePlan:
    kind: str  # "merge" | "split"
    track_ids: list[str]
    album_artist: str
    title: str
    album_id: str | None
    reason: str


def _most_common(values) -> str:
    counts = Counter(v for v in values if v)
    return counts.most_common(1)[0][0] if counts else ""


def _names(values, limit: int = 3) -> str:
    names = sorted(set(values))
    shown = ", ".join(f"'{n}'" for n in names[:limit])
    return shown + (f" and {len(names) - limit} more" if len(names) > limit else "")


def plan_album_moves(rows: list[AlbumTrackRow]) -> tuple[list[AlbumMovePlan], list[AlbumMovePlan]]:
    """The splits and merges ADR-0166 point 3 proposes, as a pure function of the tracks.

    **Splits** take back the "Various Artists" label ADR-0167's old rule wrote on a title
    another artist also used: tracks so labelled that the new rule would not label, in a
    folder holding only their artist. They move to that artist's own album.

    **Merges** join a folder's tracks that share a title but sit on several albums. A folder
    with a split pending is left alone, since its split decides where its tracks belong.
    So is a folder whose albums also hold tracks in other folders: no single folder holds
    that album, and moving its tracks here would take them out of it.
    """
    evidence_rows = [r for r in rows if r.album_artist in ("", VARIOUS_ARTISTS)]
    compilation = compilation_track_ids(
        CompilationEvidence(
            id=r.id,
            album=r.album,
            artist=r.artist,
            folder=r.folder,
            disc_number=r.disc_number,
            track_number=r.track_number,
        )
        for r in evidence_rows
    )

    artists_by_title: dict[str, set[str]] = defaultdict(set)
    artists_by_title_folder: dict[tuple[str, str], set[str]] = defaultdict(set)
    tracks_by_title_artist: Counter[tuple[str, str]] = Counter()
    number_owners: dict[tuple[str, int, int], set[str]] = defaultdict(set)
    for r in evidence_rows:
        t, a = title_key(r.album), artist_key(r.artist)
        artists_by_title[t].add(a)
        artists_by_title_folder[(t, r.folder)].add(a)
        tracks_by_title_artist[(t, a)] += 1
        if r.track_number is not None:
            number_owners[(t, r.disc_number or 1, r.track_number)].add(a)
    # An artist whose numbers collide with another's under a title: two records, not one.
    colliding: set[tuple[str, str]] = {
        (t, a) for (t, _, _), owners in number_owners.items() if len(owners) > 1 for a in owners
    }

    # Splits.
    split_groups: dict[tuple[str, str], list[AlbumTrackRow]] = defaultdict(list)
    for r in evidence_rows:
        t = title_key(r.album)
        if (
            r.album_artist == VARIOUS_ARTISTS
            and r.id not in compilation
            and len(artists_by_title[t]) > 1
            and len(artists_by_title_folder[(t, r.folder)]) == 1
            # ADR-0167 point 2's own-album test: three or more tracks, numbered as a
            # separate record. A compilation's one-track artists never qualify, even
            # when one artist holds most of it (a composer's soundtrack).
            and tracks_by_title_artist[(t, artist_key(r.artist))] >= OWN_ALBUM_MIN_TRACKS
            and (t, artist_key(r.artist)) in colliding
        ):
            split_groups[(t, artist_key(r.artist))].append(r)

    # Only where the separate records are most of the title. A compilation that happens to
    # hold one artist's three tracks (sinkfield's, of seventeen artists on *One on Twoism
    # Volume 2*) stays one record.
    title_totals: Counter[str] = Counter(title_key(r.album) for r in evidence_rows)
    own_totals: Counter[str] = Counter()
    for (t, _), group in split_groups.items():
        own_totals[t] += len(group)
    split_groups = {
        key: group for key, group in split_groups.items() if own_totals[key[0]] * 2 >= title_totals[key[0]]
    }

    in_split: set[str] = set()
    splits: list[AlbumMovePlan] = []
    for (t, a_key), group in split_groups.items():
        in_split.update(r.id for r in group)
        title = _most_common(r.album for r in group)
        artist = _most_common(r.artist for r in group)
        others = {
            r.artist for r in evidence_rows if title_key(r.album) == t and artist_key(r.artist) != a_key
        }
        splits.append(
            AlbumMovePlan(
                kind="split",
                track_ids=sorted(r.id for r in group),
                album_artist=artist,
                title=title,
                album_id=None,
                reason=(
                    f"'{title}' by {artist} was marked a compilation because {_names(others)} "
                    f"also {'has' if len(set(others)) == 1 else 'have'} an album called '{title}'. "
                    f"Moving its {len(group)} track(s) to {artist}'s own album gives each record "
                    "its own cover."
                ),
            )
        )

    # Merges.
    folders_by_album: dict[str, set[str]] = defaultdict(set)
    rows_by_album: dict[str, list[AlbumTrackRow]] = defaultdict(list)
    for r in rows:
        if r.album_id:
            folders_by_album[r.album_id].add(r.folder)
            rows_by_album[r.album_id].append(r)

    merge_groups: dict[tuple[str, str], list[AlbumTrackRow]] = defaultdict(list)
    for r in rows:
        if r.album_id:
            merge_groups[(r.folder, normalize_for_matching(r.album))].append(r)

    merges: list[AlbumMovePlan] = []
    for (folder, _), group in merge_groups.items():
        counts = Counter(r.album_id for r in group)
        if len(counts) < 2 or any(r.id in in_split for r in group):
            continue
        has_release = {r.album_id: r.album_has_release_id for r in group}
        keep = max(counts, key=lambda a: (counts[a], has_release[a], a))
        if any(folders_by_album[a] - {folder} for a in counts if a != keep):
            continue

        if folders_by_album[keep] - {folder}:
            # The kept album reaches beyond this folder. Joining it is only safe when it is
            # a compilation by ADR-0167's rule; otherwise the folders disagree about what
            # it is (*Wild Planet* under two spellings of the B-52's), and nobody can say.
            if not all(r.id in compilation for r in group if r.album_id == keep):
                continue
            album_artist = VARIOUS_ARTISTS
        elif _is_shared_rows(group):
            album_artist = VARIOUS_ARTISTS
        else:
            album_artist = _most_common(
                r.album_artist for r in group if r.album_artist not in ("", VARIOUS_ARTISTS)
            ) or _most_common(r.artist for r in group)

        moving = [r for r in group if r.album_id != keep or r.album_artist != album_artist]
        if not moving:
            continue
        labels = Counter(r.album_artist or "none" for r in group)
        described = ", ".join(
            f"{n} with album artist '{label}'" if label != "none" else f"{n} with none"
            for label, n in labels.most_common()
        )
        merges.append(
            AlbumMovePlan(
                kind="merge",
                track_ids=sorted(r.id for r in moving),
                album_artist=album_artist,
                title=_most_common(r.album for r in group),
                album_id=keep,
                reason=(
                    f"{len(group)} tracks in {folder} are on {len(counts)} albums ({described}). "
                    f"Moving them onto one gives one album and one cover, under '{album_artist}'."
                ),
            )
        )

    return splits, merges


def _is_shared_rows(rows: list[AlbumTrackRow]) -> bool:
    counts = Counter(artist_key(r.artist) for r in rows)
    return len(counts) > 1 and max(counts.values()) * 2 <= len(rows)


async def _album_track_rows(db: AsyncSession) -> list[AlbumTrackRow]:
    from pathlib import Path

    from app.db.models import Album

    stmt = (
        select(
            Track.id,
            Track.album,
            Track.artist,
            Track.album_artist,
            Track.file_path,
            Track.disc_number,
            Track.track_number,
            Track.canonical_album_id,
            Album.musicbrainz_release_id,
        )
        .outerjoin(Album, Album.id == Track.canonical_album_id)
        .where(Track.active_filter(), Track.album.isnot(None), Track.album != "")
    )
    return [
        AlbumTrackRow(
            id=str(r.id),
            album=r.album,
            artist=r.artist or "",
            album_artist=(r.album_artist or "").strip(),
            folder=str(Path(r.file_path).parent),
            disc_number=r.disc_number,
            track_number=r.track_number,
            album_id=str(r.canonical_album_id) if r.canonical_album_id else None,
            album_has_release_id=bool(r.musicbrainz_release_id),
        )
        for r in (await db.execute(stmt)).all()
    ]


async def scan_for_album_move_proposals(db: AsyncSession, *, include_splits: bool) -> int:
    """Queue ADR-0166's merge proposals, and its split proposals when asked.

    Merges run after every sync, beside the duplicate-artist scan. Splits only run by hand
    (ADR-0167 point 4): they take back labels the old compilation rule wrote, which is a
    one-off repair rather than something a sync should keep finding.

    Skips any plan sharing a track with a pending move, so two pending proposals never
    disagree about where one track belongs.
    """
    from app.services.proposed_changes import MOVE_TO_ALBUM

    splits, merges = plan_album_moves(await _album_track_rows(db))
    plans = (splits if include_splits else []) + merges

    pending = (
        await db.execute(
            select(ProposedChange.target_ids).where(
                ProposedChange.status == ChangeStatus.PENDING,
                ProposedChange.change_type == MOVE_TO_ALBUM,
            )
        )
    ).scalars()
    claimed: set[str] = {tid for ids in pending for tid in ids}

    service = ProposedChangesService(db)
    created = 0
    for plan in plans:
        if claimed.intersection(plan.track_ids):
            continue
        await service.create_change(
            change_type=MOVE_TO_ALBUM,
            target_type="album",
            target_ids=plan.track_ids,
            source=ChangeSource.AUTO_ENRICHMENT,
            field="album",
            new_value={
                "kind": plan.kind,
                "album_id": plan.album_id,
                "album_artist": plan.album_artist,
                "title": plan.title,
            },
            old_value=None,
            confidence=0.9,
            reason=plan.reason,
        )
        claimed.update(plan.track_ids)
        created += 1

    if created:
        logger.info(f"Auto-proposals: created {created} album move proposal(s)")
    return created
