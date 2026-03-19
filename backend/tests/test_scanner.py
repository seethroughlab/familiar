"""Tests for the library scanner with real audio files.

These tests use CC0-licensed audio files stored in tests/fixtures/audio/
to verify scanner functionality including:
- File discovery (including subdirectories)
- Metadata extraction
- Hash computation
- Hash-based track matching (deduplication)

Audio fixtures from: https://github.com/SoundSafari/CC0-1.0-Music

Audio fixtures structure:
  fixtures/audio/
    electronic_short.mp3              # Short test track
    electronic_short_relocated.mp3    # Duplicate for hash tests
    artist1/album1/
      ambient_loop.mp3
      orchestral_short.mp3
    artist1/album2/
      adventure.mp3
      forest_night.mp3
    artist2/album1/
      comedy_intro.mp3
    artist3/album1/
      celebration.mp3
      epic_boss_battle.mp3
"""

import shutil
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.db.models import Track, TrackStatus
from app.services.scanner import LibraryScanner, compute_file_hash, compute_full_hash
from app.utils.time import utcnow

# Path to test audio fixtures
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "audio"


@pytest_asyncio.fixture(scope="function")
async def clean_db():
    """Create a fresh database session with cleanup before and after each test.

    Creates its own engine per test to avoid event loop conflicts.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.config import settings

    # Create a fresh engine for this test (avoids event loop binding issues)
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=True,
    )

    session_maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_maker() as session:
        # Clean up before test
        await session.execute(delete(Track))
        await session.commit()

        yield session

        # Clean up after test
        await session.execute(delete(Track))
        await session.commit()

    # Dispose the engine to clean up connections
    await engine.dispose()


class TestComputeFileHash:
    """Tests for the file hash computation function."""

    def test_hash_is_consistent(self):
        """Same file should always produce the same hash."""
        test_file = FIXTURES_DIR / "electronic_short.mp3"
        hash1 = compute_file_hash(test_file)
        hash2 = compute_file_hash(test_file)
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex digest

    def test_identical_files_have_same_hash(self):
        """Identical files at different paths should have same hash."""
        file1 = FIXTURES_DIR / "electronic_short.mp3"
        file2 = FIXTURES_DIR / "electronic_short_relocated.mp3"
        assert compute_file_hash(file1) == compute_file_hash(file2)

    def test_different_files_have_different_hashes(self):
        """Different files should have different hashes."""
        file1 = FIXTURES_DIR / "electronic_short.mp3"
        file2 = FIXTURES_DIR / "artist2" / "album1" / "comedy_intro.mp3"
        assert compute_file_hash(file1) != compute_file_hash(file2)

    def test_full_hash_differs_for_same_partial_hash(self):
        """Two files with identical first/last 8KB and size but different middles
        should have the same partial hash but different full hashes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            # Build two files that share the same first 8KB, last 8KB, and total
            # size but differ in the middle.
            chunk = 8192
            head = b"\x00" * chunk
            tail = b"\xff" * chunk
            middle_size = chunk * 4  # enough to sit between head and tail

            file_a = tmp / "a.bin"
            file_b = tmp / "b.bin"

            file_a.write_bytes(head + (b"\xaa" * middle_size) + tail)
            file_b.write_bytes(head + (b"\xbb" * middle_size) + tail)

            # Sanity: same size
            assert file_a.stat().st_size == file_b.stat().st_size

            # Partial hashes MUST match (same head + tail + size)
            assert compute_file_hash(file_a) == compute_file_hash(file_b)

            # Full hashes MUST differ
            assert compute_full_hash(file_a) != compute_full_hash(file_b)


class TestMetadataExtraction:
    """Tests for metadata extraction from real audio files."""

    def test_extract_metadata_with_full_tags(self):
        """File with complete ID3 tags should extract all metadata."""
        from app.services.metadata import extract_metadata

        meta = extract_metadata(FIXTURES_DIR / "artist2" / "album1" / "comedy_intro.mp3")
        assert meta["title"] == "Silly Intro"
        assert meta["artist"] == "Alexander Nakarada"
        assert meta["duration_seconds"] is not None
        assert meta["duration_seconds"] > 0

    def test_extract_metadata_preserves_duration(self):
        """Duration should be accurately extracted."""
        from app.services.metadata import extract_metadata

        meta = extract_metadata(FIXTURES_DIR / "electronic_short.mp3")
        # This track is ~6.6 seconds
        assert 6 < meta["duration_seconds"] < 8

    def test_extract_metadata_handles_missing_title(self):
        """Files with missing title should still extract other metadata."""
        from app.services.metadata import extract_metadata

        meta = extract_metadata(FIXTURES_DIR / "artist1" / "album1" / "orchestral_short.mp3")
        # This file has artist but no title
        assert meta["artist"] == "Kevin MacLeod"
        assert meta["duration_seconds"] is not None


@pytest.mark.asyncio(loop_scope="function")
class TestLibraryScanner:
    """Integration tests for the library scanner."""

    async def test_scan_discovers_files_in_subdirectories(self, clean_db):
        """Scanner should discover all audio files recursively."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            # Copy entire fixture directory structure
            shutil.copytree(FIXTURES_DIR, tmp_path / "music")
            music_dir = tmp_path / "music"

            scanner = LibraryScanner(clean_db)
            results = await scanner.scan(music_dir)

            # Should find all 9 files (including the duplicate):
            # electronic_short.mp3, electronic_short_relocated.mp3,
            # artist1/album1/ambient_loop.mp3, artist1/album1/orchestral_short.mp3,
            # artist1/album2/adventure.mp3, artist1/album2/forest_night.mp3,
            # artist2/album1/comedy_intro.mp3,
            # artist3/album1/celebration.mp3, artist3/album1/epic_boss_battle.mp3
            assert results["total"] == 9
            # 8 are new, last one matches hash of electronic_short (relocated)
            assert results["pending_review"] == 8
            assert results["relocated"] == 1

    async def test_scan_creates_tracks_with_metadata(self, clean_db):
        """Scanned tracks should have correct metadata from subdirectories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            shutil.copytree(
                FIXTURES_DIR / "artist2" / "album1",
                tmp_path / "artist2" / "album1",
            )

            scanner = LibraryScanner(clean_db)
            await scanner.scan(tmp_path)

            # Query the created track
            result = await clean_db.execute(
                select(Track).where(Track.title == "Silly Intro")
            )
            track = result.scalar_one()

            assert track.artist == "Alexander Nakarada"
            assert track.duration_seconds is not None
            assert track.file_hash is not None
            # Path should include subdirectory structure
            assert "artist2" in track.file_path
            assert "album1" in track.file_path

    async def test_rescan_detects_unchanged_files(self, clean_db):
        """Rescanning unchanged files should report them as unchanged."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            shutil.copy(FIXTURES_DIR / "electronic_short.mp3", tmp_path)

            scanner = LibraryScanner(clean_db)

            # First scan
            results1 = await scanner.scan(tmp_path)
            assert results1["pending_review"] == 1

            # Second scan - same file
            results2 = await scanner.scan(tmp_path)
            assert results2["pending_review"] == 0
            assert results2["unchanged"] == 1

    async def test_hash_based_relocation_after_move(self, clean_db):
        """When files are moved to new directories, scanner should update paths by hash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            # Create initial directory structure
            original_dir = tmp_path / "original_location" / "artist" / "album"
            original_dir.mkdir(parents=True)
            original_file = original_dir / "track.mp3"
            shutil.copy(FIXTURES_DIR / "electronic_short.mp3", original_file)

            scanner = LibraryScanner(clean_db)

            # First scan - discovers file at original location
            results1 = await scanner.scan(tmp_path / "original_location")
            assert results1["pending_review"] == 1
            assert results1["total"] == 1

            # Get the track and verify its path
            result = await clean_db.execute(select(Track))
            track = result.scalar_one()
            original_path = track.file_path
            track_id = track.id
            assert "original_location" in original_path

            # Simulate moving the file to a completely different location
            # (like what happens when mount paths change)
            new_dir = tmp_path / "new_location" / "different" / "path"
            new_dir.mkdir(parents=True)
            new_file = new_dir / "track.mp3"
            shutil.move(original_file, new_file)

            # Scan the NEW location - should match existing track by hash
            results2 = await scanner.scan(tmp_path / "new_location")

            # Should relocate the existing track, not create a new one
            assert results2["pending_review"] == 0, "Should not create new track"
            assert results2["relocated"] == 1, "Should relocate by hash"
            assert results2["total"] == 1

            # Refresh session to see updates
            await clean_db.refresh(track)

            # Verify same track was updated with new path
            assert track.id == track_id
            assert track.file_path == str(new_file)
            assert "new_location" in track.file_path
            assert "original_location" not in track.file_path

            # Verify only one track exists in database
            result = await clean_db.execute(select(Track))
            all_tracks = result.scalars().all()
            assert len(all_tracks) == 1

    async def test_hash_matching_with_different_mount_paths(self, clean_db):
        """Same files accessed via different paths should not create duplicates.

        This simulates the real-world scenario where:
        - Files exist at /srv/dev-disk-by-uuid-.../music/...
        - Same files are also accessible via a symlink or different mount
        - Scanner should recognize them as the same files by hash
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            # Create two "mount points" with identical content
            mount1 = tmp_path / "data" / "music" / "artist" / "album"
            mount2 = tmp_path / "srv" / "dev-disk" / "music" / "artist" / "album"
            mount1.mkdir(parents=True)
            mount2.mkdir(parents=True)

            # Copy same file to both locations
            shutil.copy(FIXTURES_DIR / "electronic_short.mp3", mount1 / "song.mp3")
            shutil.copy(FIXTURES_DIR / "electronic_short.mp3", mount2 / "song.mp3")

            scanner = LibraryScanner(clean_db)

            # Scan first mount point
            results1 = await scanner.scan(tmp_path / "data")
            assert results1["pending_review"] == 1
            assert results1["total"] == 1

            # Scan second mount point - should match by hash
            results2 = await scanner.scan(tmp_path / "srv")
            assert results2["pending_review"] == 0, "Should not create duplicate"
            assert results2["relocated"] == 1, "Should relocate to new path"

            # Verify only one track exists
            result = await clean_db.execute(select(Track))
            all_tracks = result.scalars().all()
            assert len(all_tracks) == 1

            # Track should now point to the second location
            track = all_tracks[0]
            assert "srv" in track.file_path

    async def test_missing_file_marked_correctly(self, clean_db):
        """Files that disappear should be marked as missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            test_file = tmp_path / "track.mp3"
            other_file = tmp_path / "other.mp3"  # Keep one file so dir isn't empty
            shutil.copy(FIXTURES_DIR / "electronic_short.mp3", test_file)
            shutil.copy(FIXTURES_DIR / "artist2" / "album1" / "comedy_intro.mp3", other_file)

            scanner = LibraryScanner(clean_db)

            # First scan - creates 2 tracks
            await scanner.scan(tmp_path)

            # Delete one file (but keep directory non-empty)
            test_file.unlink()

            # Rescan - should mark the missing track
            results = await scanner.scan(tmp_path)
            assert results["marked_missing"] == 1

            # Check track status
            result = await clean_db.execute(
                select(Track).where(Track.title == "Quick Metal Riff 1")
            )
            track = result.scalar_one()
            assert track.status == TrackStatus.MISSING
            assert track.missing_since is not None

    async def test_recovered_file_status_restored(self, clean_db):
        """Missing files that reappear should be recovered."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            test_file = tmp_path / "track.mp3"
            other_file = tmp_path / "other.mp3"  # Keep one file so dir isn't empty
            shutil.copy(FIXTURES_DIR / "electronic_short.mp3", test_file)
            shutil.copy(FIXTURES_DIR / "artist2" / "album1" / "comedy_intro.mp3", other_file)

            scanner = LibraryScanner(clean_db)

            # Initial scan - creates 2 tracks
            await scanner.scan(tmp_path)

            # Delete one file and rescan to mark as missing
            test_file.unlink()
            await scanner.scan(tmp_path)

            # Verify it's missing
            result = await clean_db.execute(
                select(Track).where(Track.title == "Quick Metal Riff 1")
            )
            track = result.scalar_one()
            assert track.status == TrackStatus.MISSING

            # Restore file
            shutil.copy(FIXTURES_DIR / "electronic_short.mp3", test_file)

            # Rescan - should recover
            results = await scanner.scan(tmp_path)
            assert results["recovered"] == 1

            # Refresh and verify status
            await clean_db.refresh(track)
            # Recovered tracks go back to PENDING_REVIEW (their initial state from scan)
            assert track.status == TrackStatus.PENDING_REVIEW
            assert track.missing_since is None

    async def test_multi_file_relocation_to_new_structure(self, clean_db):
        """Multiple files moved to completely new directory structure should all be matched by hash.

        This tests a real-world scenario where:
        1. Library is scanned at original location
        2. User reorganizes their music (e.g., by artist/album structure)
        3. Rescan finds all files at new locations via hash matching
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            # Create initial flat directory structure with multiple files
            original_dir = tmp_path / "unsorted_music"
            original_dir.mkdir(parents=True)

            # Copy test files to flat structure (simulating messy downloads folder)
            test_files = [
                ("electronic_short.mp3", FIXTURES_DIR / "electronic_short.mp3"),
                ("comedy_intro.mp3", FIXTURES_DIR / "artist2" / "album1" / "comedy_intro.mp3"),
                ("adventure.mp3", FIXTURES_DIR / "artist1" / "album2" / "adventure.mp3"),
                ("celebration.mp3", FIXTURES_DIR / "artist3" / "album1" / "celebration.mp3"),
            ]

            for filename, source in test_files:
                shutil.copy(source, original_dir / filename)

            scanner = LibraryScanner(clean_db)

            # First scan - discovers all files in flat structure
            results1 = await scanner.scan(original_dir)
            assert results1["pending_review"] == 4, f"Expected 4 new tracks, got {results1}"
            assert results1["total"] == 4

            # Get all tracks and store their IDs for verification
            result = await clean_db.execute(select(Track))
            original_tracks = {t.file_path: (t.id, t.file_hash) for t in result.scalars().all()}
            assert len(original_tracks) == 4

            # Now simulate user reorganizing into artist/album structure
            new_base = tmp_path / "organized_library"

            # Create organized directory structure
            (new_base / "Electronic Artist" / "EP 2024").mkdir(parents=True)
            (new_base / "Comedy" / "Funny Bits").mkdir(parents=True)
            (new_base / "Adventure Soundtracks" / "Epic Journeys").mkdir(parents=True)
            (new_base / "Celebration Music" / "Party Time").mkdir(parents=True)

            # Move files to new organized locations
            shutil.move(
                original_dir / "electronic_short.mp3",
                new_base / "Electronic Artist" / "EP 2024" / "short_track.mp3"
            )
            shutil.move(
                original_dir / "comedy_intro.mp3",
                new_base / "Comedy" / "Funny Bits" / "intro_bit.mp3"
            )
            shutil.move(
                original_dir / "adventure.mp3",
                new_base / "Adventure Soundtracks" / "Epic Journeys" / "main_theme.mp3"
            )
            shutil.move(
                original_dir / "celebration.mp3",
                new_base / "Celebration Music" / "Party Time" / "party_anthem.mp3"
            )

            # Verify original directory is now empty
            remaining = list(original_dir.iterdir())
            assert len(remaining) == 0, f"Original dir should be empty, but has: {remaining}"

            # Scan the NEW organized location
            results2 = await scanner.scan(new_base)

            # All 4 files should be matched by hash, not created as new
            assert results2["pending_review"] == 0, f"Should not create new tracks, got {results2}"
            assert results2["relocated"] == 4, f"Should relocate all 4 tracks by hash, got {results2}"
            assert results2["total"] == 4

            # Verify same track IDs exist with updated paths
            result = await clean_db.execute(select(Track))
            updated_tracks = list(result.scalars().all())
            assert len(updated_tracks) == 4, "Should still have exactly 4 tracks"

            # Verify each track was updated to new path (not duplicated)
            new_paths = {t.file_path for t in updated_tracks}
            assert any("Electronic Artist" in p for p in new_paths)
            assert any("Comedy" in p for p in new_paths)
            assert any("Adventure Soundtracks" in p for p in new_paths)
            assert any("Celebration Music" in p for p in new_paths)

            # Verify old paths are no longer in database
            for old_path in original_tracks.keys():
                assert old_path not in new_paths, f"Old path {old_path} should not exist"

    async def test_scan_discovers_all_nested_subfolders(self, clean_db):
        """Scanner should discover files in deeply nested subdirectory structures."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            # Copy entire fixture directory including new nested folders
            shutil.copytree(FIXTURES_DIR, tmp_path / "music")
            music_dir = tmp_path / "music"

            scanner = LibraryScanner(clean_db)
            results = await scanner.scan(music_dir)

            # Should find all 9 unique files:
            # - electronic_short.mp3 (root)
            # - electronic_short_relocated.mp3 (root, duplicate hash)
            # - artist1/album1/ambient_loop.mp3
            # - artist1/album1/orchestral_short.mp3
            # - artist1/album2/adventure.mp3
            # - artist1/album2/forest_night.mp3
            # - artist2/album1/comedy_intro.mp3
            # - artist3/album1/celebration.mp3
            # - artist3/album1/epic_boss_battle.mp3
            assert results["total"] == 9
            # 8 unique files (electronic_short_relocated is a duplicate)
            assert results["pending_review"] == 8
            assert results["relocated"] == 1  # The duplicate


@pytest.mark.asyncio(loop_scope="function")
class TestConcurrentSyncPrevention:
    """Tests for preventing concurrent syncs (prevents duplicate tracks bug).

    The duplicate tracks bug occurred when two syncs ran concurrently:
    - Both syncs discovered files before either committed
    - Hash matching couldn't work because tracks weren't committed yet
    - Result: duplicate tracks in database

    Fix: Redis-based locking prevents concurrent syncs.
    """

    async def test_concurrent_sync_is_rejected(self, clean_db):
        """Second sync attempt should be rejected while first is running.

        This is the key test that prevents the duplicate tracks bug.
        """
        import json

        import redis

        from app.config import settings
        from app.services.background import get_background_manager

        r = redis.from_url(settings.redis_url)
        bg = get_background_manager()

        # Clean up any stale state
        r.delete("familiar:sync:lock", "familiar:sync:progress")

        try:
            # Simulate a sync already running by acquiring the lock AND setting progress
            # (lock without progress is now treated as stale/orphaned)
            lock_acquired = r.set("familiar:sync:lock", "1", nx=True, ex=60)
            assert lock_acquired, "Should acquire fresh lock"

            # Set progress with recent heartbeat (must use UTC to match background.py)
            progress = {
                "status": "running",
                "phase": "reading",
                "last_heartbeat": utcnow().isoformat(),
            }
            r.set("familiar:sync:progress", json.dumps(progress), ex=60)

            # is_sync_running should detect the lock with valid heartbeat
            assert bg.is_sync_running() is True, "Should detect running sync via Redis lock"

            # Attempting to start another sync should fail
            result = await bg.run_sync(reread_unchanged=False)
            assert result["status"] == "already_running", (
                "Second sync should be rejected when lock is held"
            )

        finally:
            # Clean up
            r.delete("familiar:sync:lock", "familiar:sync:progress")

    async def test_sync_lock_is_released_after_completion(self, clean_db):
        """Sync lock should be released after sync completes (success or failure)."""
        import redis

        from app.config import settings

        r = redis.from_url(settings.redis_url)

        # Clean up any stale lock
        r.delete("familiar:sync:lock")

        try:
            # Acquire lock manually
            r.set("familiar:sync:lock", "1", nx=True, ex=60)
            assert r.get("familiar:sync:lock") is not None

            # Release lock (as would happen after sync)
            r.delete("familiar:sync:lock")

            # Verify lock is released
            assert r.get("familiar:sync:lock") is None

        finally:
            r.delete("familiar:sync:lock")

    async def test_stale_lock_detection_via_heartbeat(self, clean_db):
        """Stale syncs (no heartbeat) should not block new syncs."""
        import json
        from datetime import datetime, timedelta

        import redis

        from app.config import settings
        from app.services.background import get_background_manager

        r = redis.from_url(settings.redis_url)
        bg = get_background_manager()

        # Clean up Redis and local task state
        r.delete("familiar:sync:lock")
        r.delete("familiar:sync:progress")
        bg._current_sync_task = None  # Reset local task state from previous tests

        try:
            # Create stale progress (old heartbeat, no lock)
            stale_progress = {
                "status": "running",
                "last_heartbeat": (datetime.now() - timedelta(minutes=10)).isoformat(),
            }
            r.set("familiar:sync:progress", json.dumps(stale_progress))

            # Should NOT detect as running (heartbeat too old)
            assert bg.is_sync_running() is False, (
                "Stale sync (old heartbeat) should not block new syncs"
            )

        finally:
            r.delete("familiar:sync:lock")
            r.delete("familiar:sync:progress")
