"""Album artwork extraction and management service."""

import hashlib
import subprocess
import tempfile
import time
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from typing import Any

import mutagen
from mutagen.flac import FLAC
from mutagen.id3 import ID3
from mutagen.mp4 import MP4
from PIL import Image

from app.config import GENERATIVE_ART_VERSION, settings

# Standard sizes for artwork
ARTWORK_SIZES = {
    "full": 500,      # Full size for player view
    "thumb": 200,     # Thumbnail for lists
}


def _generated_marker_path(album_key: str) -> Path:
    """Get the path for the .generated marker file.

    Note the `full` variant has no suffix, so a `f"{album_key}*"` glob also matches the
    thumb and this marker. Fine for moving files, dangerous for deleting them —
    `fix_album_art.py` deletes the two JPEGs and leaves the marker behind, which is why
    a regenerated album can come back as generated art.
    """
    return settings.art_path / f"{album_key}.generated"


def is_generated_artwork(album_key: str) -> bool:
    """Check if artwork for this album hash was generated (not real art)."""
    return _generated_marker_path(album_key).exists()


def mark_as_generated(album_key: str) -> None:
    """Create a .generated marker file with current art version."""
    settings.art_path.mkdir(parents=True, exist_ok=True)
    _generated_marker_path(album_key).write_text(str(GENERATIVE_ART_VERSION))


#: How long a placeholder stands before the internet is asked again.
#:
#: A generated cover means "Last.fm and MusicBrainz had nothing when we asked". That can stop being
#: true — art gets added, and a tag correction changes what we ask for — so it is worth asking again,
#: but not often: an album that genuinely has no art online would otherwise be looked up every time
#: it scrolled into view, forever. Thirty days is roughly twenty lookups a day across a 4k library.
ARTWORK_REFETCH_INTERVAL = timedelta(days=30)


def should_refetch_online(album_key: str) -> bool:
    """True when the art on disk is a placeholder old enough to try the internet again.

    **This is the rule that decides whether artwork already on disk counts as "done".** It exists
    because the obvious test — does the file exist — answers yes for a picture Familiar drew itself,
    which is how 661 albums came to be permanently stuck on placeholders: both queue routes
    short-circuited on ``full_path.exists()`` and reported ``"exists"``, so the fetcher's own
    allowance for re-queueing generated art was unreachable through the API.

    Real art returns ``False`` — no marker, nothing to retry, and a successful fetch is never redone.

    The marker's mtime is "when we last tried online", which needs no new file and no migration:
    ``mark_as_generated`` writes it at the end of every failed fetch. Note that re-drawing a
    placeholder (``/artwork/regenerate``) rewrites the marker and so restarts the clock — acceptable,
    because a redraw is also a deliberate act on that album.
    """
    marker = _generated_marker_path(album_key)
    try:
        age = time.time() - marker.stat().st_mtime
    except OSError:
        # No marker: either real art, or nothing at all. Neither is a placeholder to replace.
        return False
    return age >= ARTWORK_REFETCH_INTERVAL.total_seconds()


def is_generated_art_current(album_key: str) -> bool:
    """Check if generated artwork matches the current art version.

    Returns False if not generated, marker missing, or version is stale.
    """
    marker = _generated_marker_path(album_key)
    if not marker.exists():
        return False
    try:
        return int(marker.read_text().strip()) >= GENERATIVE_ART_VERSION
    except (ValueError, OSError):
        return False


def clear_generated_marker(album_key: str) -> None:
    """Remove the .generated marker (real art is replacing generated art)."""
    _generated_marker_path(album_key).unlink(missing_ok=True)


def get_artwork_path(album_key: str, size: str = "full") -> Path:
    """Get the file path for artwork.

    Args:
        album_key: Identifies the album on disk. Since ADR-0052 this is an ``Album.id``
            for anything resolved; it is still a ``compute_album_hash`` value for tracks
            the resolver could not place. Both are opaque filename-safe strings, which
            is the only property this function needs.
        size: Size variant ('full' or 'thumb')

    Returns:
        Path to artwork file
    """
    suffix = f"_{size}" if size != "full" else ""
    return settings.art_path / f"{album_key}{suffix}.jpg"


def compute_album_hash(artist: str | None, album: str | None) -> str:
    """The legacy artwork key: a hash of the normalized artist and album.

    **Superseded by ``Album.id`` (ADR-0052), and kept rather than deleted.** It is the
    fallback for a track the resolver could not place, and the artwork migration needs
    it to work out which album each existing file on disk belongs to — nothing in the
    database ever recorded that, so recomputing this is the only way back from a
    filename.

    Its two defects are the reason ADR-0052 exists. It uses ``artist`` rather than
    ``album_artist``, so a compilation gets one key per track artist; and it is derived
    from the values a person can edit, so correcting a spelling silently re-keys the
    artwork to a slot nothing has ever fetched.
    """
    from app.services.normalize import normalize_for_matching

    artist_norm = normalize_for_matching(artist) or "unknown"
    album_norm = normalize_for_matching(album) or "unknown"
    key = f"{artist_norm}::{album_norm}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def album_key_for_track(track: Any) -> str:
    """The artwork key for a track (ADR-0052).

    Its canonical album id when the resolver placed it, and the legacy hash when it did
    not. **The fallback is what makes the rollout safe**: before the backfill runs, every
    track has a null ``canonical_album_id`` and this behaves exactly as it did before, so
    the schema can ship and be deployed without the artwork moving underneath anyone.

    After the backfill and the file migration, only tracks the resolver genuinely could
    not place — no album tag and no path — stay on a hash.
    """
    album_id = getattr(track, "canonical_album_id", None)
    if album_id:
        return str(album_id)
    return compute_album_hash(
        getattr(track, "artist", None), getattr(track, "album", None)
    )


def _extract_ffmpeg_artwork(file_path: Path) -> bytes | None:
    """Extract artwork using ffmpeg (for formats with attached picture streams)."""
    try:
        # Create temp file for extracted artwork
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = tmp.name

        # Use ffmpeg to extract the video stream (attached picture)
        cmd = [
            "ffmpeg", "-y", "-i", str(file_path),
            "-an",  # No audio
            "-vcodec", "mjpeg",  # Output as JPEG
            "-frames:v", "1",  # Just one frame
            tmp_path
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=30,
        )

        if result.returncode == 0:
            tmp_file = Path(tmp_path)
            if tmp_file.exists() and tmp_file.stat().st_size > 0:
                artwork_data = tmp_file.read_bytes()
                tmp_file.unlink()
                return artwork_data

        # Clean up on failure
        Path(tmp_path).unlink(missing_ok=True)
    except Exception:
        pass

    return None


def extract_artwork(file_path: Path) -> bytes | None:  # type: ignore[return]
    """Extract embedded artwork from audio file.

    Supports MP3 (ID3), FLAC, M4A (MP4), and AIFF/WAV (attached pictures).

    Returns:
        Raw image bytes or None if no artwork found.
    """
    suffix = file_path.suffix.lower()

    try:
        if suffix == ".mp3":
            return _extract_id3_artwork(file_path)
        elif suffix == ".flac":
            return _extract_flac_artwork(file_path)
        elif suffix in {".m4a", ".aac", ".mp4"}:
            return _extract_mp4_artwork(file_path)
        elif suffix in {".aiff", ".aif", ".wav"}:
            # AIFF/WAV files often have artwork as attached picture streams
            # Try ffmpeg first, then fall back to ID3
            result = _extract_ffmpeg_artwork(file_path)
            if result:
                return result
            return _extract_id3_artwork(file_path)
        else:
            # Try generic mutagen approach
            audio = mutagen.File(file_path)  # type: ignore[attr-defined]
            if audio and hasattr(audio, "pictures") and audio.pictures:
                return audio.pictures[0].data
            # Also try ID3 as fallback (some formats embed ID3 chunks)
            result = _extract_id3_artwork(file_path)
            if result:
                return result
    except Exception as e:
        print(f"Error extracting artwork from {file_path}: {e}")

    return None


def _extract_id3_artwork(file_path: Path) -> bytes | None:  # type: ignore[return]
    """Extract artwork from ID3 tags (MP3)."""
    try:
        tags = ID3(file_path)  # type: ignore[no-untyped-call]
        # Look for APIC (Attached Picture) frames
        for key in tags.keys():
            if key.startswith("APIC"):
                return tags[key].data  # type: ignore[return-value]
    except Exception:
        pass
    return None


def _extract_flac_artwork(file_path: Path) -> bytes | None:  # type: ignore[return]
    """Extract artwork from FLAC metadata."""
    try:
        audio = FLAC(file_path)  # type: ignore[no-untyped-call]
        if audio.pictures:
            # Prefer front cover (type 3) if available
            for pic in audio.pictures:
                if pic.type == 3:  # Front cover
                    return pic.data  # type: ignore[return-value]
            # Fall back to first picture
            return audio.pictures[0].data  # type: ignore[return-value]
    except Exception:
        pass
    return None


def _extract_mp4_artwork(file_path: Path) -> bytes | None:  # type: ignore[return]
    """Extract artwork from MP4/M4A atoms."""
    try:
        audio = MP4(file_path)  # type: ignore[no-untyped-call]
        if audio.tags and "covr" in audio.tags:
            covers = audio.tags["covr"]
            if covers:
                return bytes(covers[0])  # type: ignore[return-value]
    except Exception:
        pass
    return None


def save_artwork(
    image_data: bytes,
    album_key: str,
    sizes: dict[str, int] | None = None,
) -> dict[str, Path]:
    """Save artwork to disk in multiple sizes.

    Args:
        image_data: Raw image bytes
        album_key: Hash identifying the album
        sizes: Dict of size names to max dimensions. Defaults to ARTWORK_SIZES.

    Returns:
        Dict mapping size names to saved file paths.
    """
    if sizes is None:
        sizes = ARTWORK_SIZES

    # Ensure art directory exists
    settings.art_path.mkdir(parents=True, exist_ok=True)

    saved_paths: dict[str, Path] = {}

    # Clear generated marker — real art replaces generated
    clear_generated_marker(album_key)

    try:
        # Open image with Pillow
        img = Image.open(BytesIO(image_data))

        # Convert to RGB if necessary (for JPEG output)
        if img.mode in ("RGBA", "P"):
            rgb_img = img.convert("RGB")
            img = rgb_img

        from app.utils.atomic_write import atomic_write_via

        for size_name, max_dim in sizes.items():
            output_path = get_artwork_path(album_key, size_name)

            # Resize maintaining aspect ratio
            img_copy = img.copy()
            img_copy.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

            # Save as JPEG atomically
            atomic_write_via(
                output_path,
                lambda p, _img=img_copy: _img.save(p, "JPEG", quality=85, optimize=True),
            )
            saved_paths[size_name] = output_path

    except Exception as e:
        print(f"Error saving artwork: {e}")

    return saved_paths


def extract_and_save_artwork(
    file_path: Path,
    artist: str | None,
    album: str | None,
    *,
    album_key: str | None = None,
) -> str | None:
    """Extract artwork from a file's tags and save it under the album's key.

    Args:
        file_path: Path to audio file
        artist: Artist name, used only to derive the legacy key
        album: Album name, used only to derive the legacy key
        album_key: The album's key (ADR-0052). Pass ``str(track.canonical_album_id)``
            where a track is in hand; omitted, this falls back to the legacy hash, which
            keeps the callers that have only tag strings working.

    Returns:
        The album key if artwork was saved, None otherwise.
    """
    album_key = album_key or compute_album_hash(artist, album)

    # Check if artwork already exists
    full_path = get_artwork_path(album_key, "full")
    if full_path.exists():
        return album_key

    # Extract artwork from file
    image_data = extract_artwork(file_path)
    if not image_data:
        return None

    # Save artwork
    saved = save_artwork(image_data, album_key)
    if saved:
        return album_key

    return None
