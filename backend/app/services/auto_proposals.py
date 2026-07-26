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
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChangeSource, ChangeStatus, ProposedChange, Track
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
            return await scan_for_duplicate_artist_proposals(db)
    finally:
        await engine.dispose()
