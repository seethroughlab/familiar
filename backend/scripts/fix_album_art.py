#!/usr/bin/env python3
"""Fix incorrect album artwork for a specific album.

This script:
1. Finds all tracks from the specified artist/album
2. Deletes the cached album artwork
3. Clears the cached MusicBrainz release ID from track analysis
4. Re-enriches the tracks to fetch correct artwork

Usage:
    # From backend directory on openmediavault:
    cd /path/to/familiar/backend

    # Make sure environment variables are set:
    export DATABASE_URL="postgresql+asyncpg://familiar:familiar@localhost:5432/familiar"
    export REDIS_URL="redis://localhost:6379/0"

    # Then run:
    uv run python scripts/fix_album_art.py "Sigur Rós" "()"

    # Or with different artist/album:
    uv run python scripts/fix_album_art.py "Artist Name" "Album Name"
"""

import asyncio
import os
import sys
from pathlib import Path

# Add the app to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Check environment variables
if not os.environ.get("DATABASE_URL"):
    print("Error: DATABASE_URL environment variable not set")
    print("Example: export DATABASE_URL='postgresql+asyncpg://familiar:familiar@localhost:5432/familiar'")
    sys.exit(1)


async def fix_album_art(artist: str, album: str) -> None:
    """Fix album artwork for a specific artist/album."""
    from sqlalchemy import select

    from app.db.models import Track, TrackAnalysis, TrackStatus
    from app.db.session import async_session_maker
    from app.services.artwork import (
        ARTWORK_SIZES,
        album_key_for_track,
        clear_generated_marker,
        get_artwork_path,
    )
    from app.services.tasks import run_track_enrichment

    print(f"Fixing album art for: {artist} - {album}")
    print("-" * 50)

    # Step 1: Find tracks
    async with async_session_maker() as db:
        query = (
            select(Track)
            .where(
                Track.artist == artist,
                Track.album == album,
                Track.status == TrackStatus.ACTIVE,
            )
        )
        result = await db.execute(query)
        tracks = result.scalars().all()

        if not tracks:
            print(f"No tracks found for {artist} - {album}")
            print("Trying case-insensitive search...")

            # Try case-insensitive
            from sqlalchemy import func
            query = (
                select(Track)
                .where(
                    func.lower(Track.artist) == artist.lower(),
                    func.lower(Track.album) == album.lower(),
                    Track.status == TrackStatus.ACTIVE,
                )
            )
            result = await db.execute(query)
            tracks = result.scalars().all()

            if not tracks:
                print("Still no tracks found. Check the artist/album spelling.")
                return

        print(f"Found {len(tracks)} tracks")

        # Get actual artist/album from database (may have different casing)
        actual_artist = tracks[0].artist
        actual_album = tracks[0].album
        print(f"Actual values: {actual_artist} - {actual_album}")

        # Step 2: Delete cached artwork
        album_key = album_key_for_track(tracks[0])
        print(f"\nAlbum key: {album_key}")

        # The marker goes too. Deleting only the JPEGs left `.generated` behind, so the
        # album still counted as generated art and `/artwork/regenerate` would refuse to
        # replace whatever arrived next — a repair tool that quietly half-repaired.
        clear_generated_marker(album_key)

        deleted_art = 0
        for size in ARTWORK_SIZES:
            art_path = get_artwork_path(album_key, size)
            if art_path.exists():
                art_path.unlink()
                print(f"  Deleted: {art_path}")
                deleted_art += 1

        if deleted_art == 0:
            print("  No cached artwork found")

        # Step 3: Clear MusicBrainz release ID from track analysis
        track_ids = [t.id for t in tracks]
        print(f"\nClearing MusicBrainz release IDs for {len(track_ids)} tracks...")

        # Get analysis records and clear their features
        for track in tracks:
            # Get track analysis
            analysis_query = select(TrackAnalysis).where(TrackAnalysis.track_id == track.id)
            analysis_result = await db.execute(analysis_query)
            analysis = analysis_result.scalar_one_or_none()

            if analysis and analysis.features:
                features = dict(analysis.features)  # Make a copy
                if "musicbrainz" in features:
                    mb_data = features["musicbrainz"]
                    old_release = mb_data.get("musicbrainz_release_id", "none")
                    old_album = mb_data.get("album", "none")
                    print(f"  Track: {track.title}")
                    print(f"    Old release ID: {old_release}")
                    print(f"    Old album: {old_album}")

                    # Clear the release ID so it gets re-fetched
                    del features["musicbrainz"]
                    analysis.features = features

        await db.commit()
        print("\nCleared MusicBrainz data from analysis records")

        # Step 4: Re-enrich the tracks
        print(f"\nRe-enriching {len(tracks)} tracks...")
        print("(This may take a while due to MusicBrainz rate limiting - 1 request/second)")

        for i, track in enumerate(tracks, 1):
            print(f"  [{i}/{len(tracks)}] {track.title}...", end=" ", flush=True)
            try:
                result = await run_track_enrichment(str(track.id))
                status = result.get("status", "unknown")
                if status == "enriched":
                    new_album = result.get("album", "?")
                    print(f"OK (album: {new_album})")
                else:
                    print(f"{status}")
            except Exception as e:
                print(f"Error: {e}")

    print("\n" + "=" * 50)
    print("Done! Refresh the UI to see updated artwork.")


def main():
    if len(sys.argv) < 3:
        print("Usage: python fix_album_art.py <artist> <album>")
        print('Example: python fix_album_art.py "Sigur Rós" "()"')
        sys.exit(1)

    artist = sys.argv[1]
    album = sys.argv[2]

    asyncio.run(fix_album_art(artist, album))


if __name__ == "__main__":
    main()
