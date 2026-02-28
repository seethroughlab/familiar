"""Metadata enrichment tasks: MusicBrainz lookup, artwork, tag writing.

Contains run_track_enrichment and propose_enrichment_for_track.
"""

import logging
from datetime import datetime
from app.utils.time import utcnow
from pathlib import Path
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


async def run_track_enrichment(track_id: str) -> dict[str, Any]:
    """Enrich a track's metadata from MusicBrainz/AcoustID.

    This runs asynchronously as a background task.

    Actions:
    1. Look up track via AcoustID fingerprint
    2. Fetch full metadata from MusicBrainz
    3. Download album art from Cover Art Archive
    4. Write metadata to ID3 tags (respecting overwrite setting)
    5. Embed artwork in file
    6. Save artwork to data/art/
    7. Update database
    """
    from sqlalchemy import select

    from app.db.models import Track
    from app.db.session import create_task_engine_session
    from app.services.analysis import lookup_acoustid
    from app.services.app_settings import get_app_settings_service
    from app.services.artwork import compute_album_hash, save_artwork
    from app.services.import_service import embed_artwork
    from app.services.metadata.enrichment import (
        fetch_cover_art,
        needs_enrichment,
        write_metadata_to_file,
    )
    from app.services.metadata.musicbrainz import enrich_track

    result: dict[str, Any] = {
        "track_id": track_id,
        "status": "skipped",
        "fields_updated": [],
        "artwork_saved": False,
        "tags_written": False,
    }

    # Get settings
    app_settings = get_app_settings_service().get()
    overwrite_existing = app_settings.enrich_overwrite_existing

    local_engine, local_session_maker = create_task_engine_session()

    try:
        async with local_session_maker() as db:
            stmt = select(Track).where(Track.id == UUID(track_id))
            query_result = await db.execute(stmt)
            track = query_result.scalar_one_or_none()

            if not track:
                return {"status": "error", "error": "Track not found", **result}

            file_path = Path(track.file_path)
            if not file_path.exists():
                return {"status": "error", "error": "File not found", **result}

            # Check if enrichment is still needed
            if not needs_enrichment(track):
                return {"status": "skipped", "reason": "metadata complete", **result}

            logger.info(f"Enriching metadata for: {track.artist} - {track.title}")

            # Step 1: Lookup via AcoustID
            musicbrainz_id = None
            try:
                acoustid_result = lookup_acoustid(file_path)
                if acoustid_result:
                    musicbrainz_id = acoustid_result.get("musicbrainz_recording_id")
            except Exception as e:
                logger.debug(f"AcoustID lookup failed: {e}")

            # Step 2: Enrich from MusicBrainz
            mb_metadata = enrich_track(
                title=track.title,
                artist=track.artist,
                album=track.album,
                musicbrainz_recording_id=musicbrainz_id,
            )

            if not mb_metadata:
                return {"status": "no_match", "error": "No MusicBrainz match found", **result}

            # Step 3: Prepare metadata updates
            updates: dict[str, Any] = {}
            file_metadata: dict[str, Any] = {}

            def should_update(field: str, db_value: Any) -> bool:
                if overwrite_existing:
                    return True
                return db_value is None or (isinstance(db_value, str) and not db_value.strip())

            if mb_metadata.get("title") and should_update("title", track.title):
                updates["title"] = mb_metadata["title"]
                file_metadata["title"] = mb_metadata["title"]

            if mb_metadata.get("artist") and should_update("artist", track.artist):
                updates["artist"] = mb_metadata["artist"]
                file_metadata["artist"] = mb_metadata["artist"]

            if mb_metadata.get("album") and should_update("album", track.album):
                updates["album"] = mb_metadata["album"]
                file_metadata["album"] = mb_metadata["album"]

            if mb_metadata.get("tags") and should_update("genre", track.genre):
                genre = mb_metadata["tags"][0] if mb_metadata["tags"] else None
                if genre:
                    updates["genre"] = genre
                    file_metadata["genre"] = genre

            if mb_metadata.get("release_date") and should_update("year", track.year):
                try:
                    year = int(mb_metadata["release_date"][:4])
                    updates["year"] = year
                    file_metadata["year"] = year
                except (ValueError, IndexError):
                    pass

            # Store MusicBrainz IDs (always update these)
            if mb_metadata.get("musicbrainz_recording_id"):
                updates["musicbrainz_track_id"] = mb_metadata["musicbrainz_recording_id"]
            if mb_metadata.get("musicbrainz_release_id"):
                updates["musicbrainz_album_id"] = mb_metadata["musicbrainz_release_id"]
            if mb_metadata.get("musicbrainz_artist_ids"):
                updates["musicbrainz_artist_id"] = mb_metadata["musicbrainz_artist_ids"][0]

            # Step 4: Fetch album art from Cover Art Archive
            release_id = mb_metadata.get("musicbrainz_release_id")
            artwork_data = None
            if release_id:
                artwork_data = await fetch_cover_art(release_id)

            # Step 5: Write ID3 tags to file
            if file_metadata:
                tags_written = write_metadata_to_file(
                    file_path, file_metadata, overwrite_existing
                )
                result["tags_written"] = tags_written

            # Step 6: Embed and save artwork
            if artwork_data:
                # Embed in file
                try:
                    embed_artwork(file_path, artwork_data)
                except Exception as e:
                    logger.warning(f"Failed to embed artwork: {e}")

                # Save to art folder
                artist_for_hash = updates.get("artist") or track.artist
                album_for_hash = updates.get("album") or track.album
                album_hash = compute_album_hash(artist_for_hash, album_for_hash)
                try:
                    save_artwork(artwork_data, album_hash)
                    result["artwork_saved"] = True
                except Exception as e:
                    logger.warning(f"Failed to save artwork: {e}")

            # Step 7: Update database
            if updates:
                for key, value in updates.items():
                    setattr(track, key, value)
                track.updated_at = utcnow()
                await db.commit()

            result["status"] = "success"
            result["fields_updated"] = list(updates.keys())

            logger.info(
                f"Enriched track {track_id}: updated {list(updates.keys())}, "
                f"artwork={'yes' if artwork_data else 'no'}"
            )

    except Exception as e:
        logger.error(f"Enrichment failed for {track_id}: {e}", exc_info=True)
        result["status"] = "error"
        result["error"] = str(e)
    finally:
        await local_engine.dispose()

    return result


async def propose_enrichment_for_track(track_id: str) -> dict[str, Any]:
    """Propose metadata enrichment for a track with incomplete metadata.

    This runs asynchronously as a background task when a track is played.
    Unlike run_track_enrichment (which directly modifies files), this creates
    a ProposedChange for the user to review.

    Actions:
    1. Check if track already has a pending proposal
    2. Look up track metadata via MusicBrainz
    3. If confident match found (>0.8), create ProposedChange
    """
    from sqlalchemy import select

    from app.db.models import ChangeSource, ChangeStatus, ProposedChange, Track
    from app.db.session import create_task_engine_session
    from app.services.metadata.enrichment import get_missing_fields
    from app.services.metadata.lookup import MetadataLookupService
    from app.services.proposed_changes import ProposedChangesService

    result: dict[str, Any] = {
        "track_id": track_id,
        "status": "skipped",
        "reason": None,
        "proposal_created": False,
    }

    local_engine, local_session_maker = create_task_engine_session()

    try:
        async with local_session_maker() as db:
            # Get the track
            stmt = select(Track).where(Track.id == UUID(track_id))
            query_result = await db.execute(stmt)
            track = query_result.scalar_one_or_none()

            if not track:
                result["reason"] = "Track not found"
                return result

            # Check if track already has a pending proposal
            existing_stmt = select(ProposedChange).where(
                ProposedChange.target_ids.contains([track_id]),
                ProposedChange.status == ChangeStatus.PENDING,
                ProposedChange.source == ChangeSource.AUTO_ENRICHMENT,
            )
            existing_result = await db.execute(existing_stmt)
            if existing_result.scalar_one_or_none():
                result["reason"] = "Pending proposal already exists"
                return result

            # Get missing fields
            missing_fields = get_missing_fields(track)
            if not missing_fields:
                result["reason"] = "No missing fields"
                return result

            # Look up metadata from MusicBrainz
            lookup_service = MetadataLookupService()

            # We need at least title and artist to look up
            title = track.title or ""
            artist = track.artist or ""
            if not title or not artist:
                result["reason"] = "Track missing title or artist for lookup"
                return result

            candidates = await lookup_service.lookup_track(
                title=title,
                artist=artist,
                album=track.album,
                limit=1,
            )

            if not candidates:
                result["reason"] = "No MusicBrainz matches found"
                return result

            best_match = candidates[0]
            if best_match.confidence < 0.8:
                result["reason"] = f"Match confidence too low ({best_match.confidence:.2f})"
                return result

            # Create proposed changes for each missing field that has a value
            service = ProposedChangesService(db)
            proposals_created = 0

            for field in missing_fields:
                new_value = best_match.metadata.get(field)
                if new_value:
                    await service.create_change(
                        change_type="metadata",
                        target_type="track",
                        target_ids=[track_id],
                        source=ChangeSource.AUTO_ENRICHMENT,
                        field=field,
                        old_value=getattr(track, field, None),
                        new_value=new_value,
                        source_detail=f"MusicBrainz: {best_match.source_id}",
                        confidence=best_match.confidence,
                        reason=f"Auto-detected missing {field} during playback",
                    )
                    proposals_created += 1

            if proposals_created > 0:
                result["status"] = "success"
                result["proposal_created"] = True
                result["fields_proposed"] = [
                    f for f in missing_fields if best_match.metadata.get(f)
                ]
                logger.info(
                    f"Created {proposals_created} enrichment proposal(s) for track {track_id}"
                )
            else:
                result["reason"] = "No enrichable fields found in MusicBrainz data"

    except Exception as e:
        logger.error(f"Auto-enrichment proposal failed for {track_id}: {e}", exc_info=True)
        result["status"] = "error"
        result["error"] = str(e)
    finally:
        await local_engine.dispose()

    return result
