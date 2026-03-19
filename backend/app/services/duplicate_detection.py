"""Shared duplicate detection for import preview and scanner.

Extracted from library_import/preview.py so the scanner can reuse
the same logic when populating review_info for pending tracks.
"""

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Track, TrackStatus
from app.services.quality import calculate_quality_score, compare_quality

logger = logging.getLogger(__name__)


async def find_import_duplicate(
    db: AsyncSession,
    artist: str,
    album: str,
    title: str,
) -> tuple["Track | None", str]:
    """Multi-phase duplicate detection.

    Only matches against ACTIVE tracks so PENDING_REVIEW and SKIPPED
    tracks aren't returned as duplicates.

    Returns (matching_track, match_type) where match_type is one of:
    "exact", "normalized", "artist_title", or "" if no match.
    """
    from app.services.normalize import normalize_for_duplicate_matching

    active_filter = Track.status == TrackStatus.ACTIVE

    # Phase 1: Exact case-insensitive match (artist + album + title)
    if album:
        stmt = (
            select(Track)
            .where(
                active_filter,
                func.lower(Track.artist) == artist.lower(),
                func.lower(Track.album) == album.lower(),
                func.lower(Track.title) == title.lower(),
            )
            .limit(1)
        )
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing:
            return existing, "exact"

    # Phase 2: Fetch candidates by artist variants for fuzzy matching
    artist_lower = artist.lower()
    artist_variants = [artist_lower]

    for article in ("the ", "a ", "an "):
        if artist_lower.startswith(article):
            artist_variants.append(artist_lower[len(article):])
        else:
            artist_variants.append(article + artist_lower)

    stmt = (
        select(Track)
        .where(active_filter, func.lower(Track.artist).in_(artist_variants))
    )
    candidates = (await db.execute(stmt)).scalars().all()

    if not candidates:
        return None, ""

    # Phase 3: Normalized artist + album + title
    norm_artist = normalize_for_duplicate_matching(artist, strip_articles=True)
    norm_album = normalize_for_duplicate_matching(album)
    norm_title = normalize_for_duplicate_matching(title)

    if norm_album:
        for candidate in candidates:
            if (
                normalize_for_duplicate_matching(candidate.artist, strip_articles=True) == norm_artist
                and normalize_for_duplicate_matching(candidate.album) == norm_album
                and normalize_for_duplicate_matching(candidate.title) == norm_title
            ):
                return candidate, "normalized"

    # Phase 4: Artist + title only (no album requirement)
    for candidate in candidates:
        if (
            normalize_for_duplicate_matching(candidate.artist, strip_articles=True) == norm_artist
            and normalize_for_duplicate_matching(candidate.title) == norm_title
        ):
            return candidate, "artist_title"

    return None, ""


async def enrich_tracks_with_duplicates(
    db: AsyncSession,
    tracks: list[dict],
) -> None:
    """Enrich track dicts with duplicate detection and quality comparison info.

    Mutates tracks in-place, adding duplicate_of, trump_status, etc.
    """
    for track in tracks:
        artist = track.get("detected_artist") or ""
        album = track.get("detected_album") or ""
        title = track.get("detected_title") or ""

        if not (artist and title):
            continue

        existing, match_type = await find_import_duplicate(
            db, artist, album, title
        )

        if not existing:
            continue

        track["duplicate_of"] = str(existing.id)
        track["duplicate_info"] = (
            f"{existing.artist} - {existing.album} - {existing.title}"
        )
        track["duplicate_match_type"] = match_type

        incoming_score = calculate_quality_score(
            format=track.get("format"),
            bitrate=track.get("bitrate"),
            sample_rate=track.get("sample_rate"),
            bit_depth=track.get("bit_depth"),
            bitrate_mode=track.get("bitrate_mode"),
        )
        existing_score = calculate_quality_score(
            format=existing.format,
            bitrate=existing.bitrate,
            sample_rate=existing.sample_rate,
            bit_depth=existing.bit_depth,
            bitrate_mode=existing.bitrate_mode,
        )

        trump_status, trump_reason = compare_quality(
            incoming_score, existing_score
        )
        track["trump_status"] = trump_status
        track["trump_reason"] = trump_reason
        track["incoming_quality"] = incoming_score.to_dict()
        track["existing_quality"] = existing_score.to_dict()


async def detect_duplicate_for_track(
    db: AsyncSession,
    track: Track,
) -> dict[str, Any] | None:
    """Run duplicate detection for a Track model instance.

    Returns a review_info dict if a duplicate is found, or None.
    """
    artist = track.artist or ""
    title = track.title or ""

    if not (artist and title):
        return None

    existing, match_type = await find_import_duplicate(
        db, artist, track.album or "", title
    )

    if not existing:
        return None

    incoming_score = calculate_quality_score(
        format=track.format,
        bitrate=track.bitrate,
        sample_rate=track.sample_rate,
        bit_depth=track.bit_depth,
        bitrate_mode=track.bitrate_mode,
    )
    existing_score = calculate_quality_score(
        format=existing.format,
        bitrate=existing.bitrate,
        sample_rate=existing.sample_rate,
        bit_depth=existing.bit_depth,
        bitrate_mode=existing.bitrate_mode,
    )

    trump_status, trump_reason = compare_quality(incoming_score, existing_score)

    return {
        "duplicate_of": str(existing.id),
        "duplicate_info": f"{existing.artist} - {existing.album} - {existing.title}",
        "duplicate_match_type": match_type,
        "trump_status": trump_status,
        "trump_reason": trump_reason,
        "incoming_quality": incoming_score.to_dict(),
        "existing_quality": existing_score.to_dict(),
    }
