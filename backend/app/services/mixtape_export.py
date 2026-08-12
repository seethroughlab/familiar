"""Mix Tape Export — render a playlist into a single MP3 with cover and tracklist.

Pipeline:
  resolve_tracks → render_audio (ffmpeg) → generate_cover (Pillow)
  → write_tracklist → embed_tags (mutagen) → bundle_zip

The render is intentionally lossy — 128 kbps MP3 with a 15 kHz low-pass —
to discourage re-distribution as a clean rip while still sounding pleasant.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import subprocess
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID

from mutagen.id3 import (
    APIC,
    CHAP,
    CTOC,
    ID3,
    TALB,
    TCON,
    TIT2,
    TPE1,
    TPE2,
    TPE4,
    TYER,
    CTOCFlags,
)
from mutagen.id3._util import ID3NoHeaderError
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db.models import (
    MixTape,
    Playlist,
    PlaylistTrack,
    Track,
)
from app.services.artwork import album_key_for_track, get_artwork_path
from app.services.smart_playlists import SmartPlaylistService
from app.utils.time import utcnow

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────────────

MIN_TRACKS = 2
MAX_TRACKS = 15
COVER_SIZE = 1000
TARGET_SAMPLE_RATE = 44100
LOW_PASS_HZ = 15000
BITRATE = "128k"
DEFAULT_CROSSFADE_CURVE = "qsin"  # equal-power


# ── Data containers ─────────────────────────────────────────────────────────


@dataclass
class RenderResult:
    """Output of render_audio."""

    audio_path: Path
    segment_offsets: list[float]  # seconds, len == len(tracks)
    total_duration: float


# ── Track resolution ────────────────────────────────────────────────────────


async def resolve_tracks(
    db: AsyncSession,
    source_playlist_id: UUID | None,
    source_smart_playlist_id: UUID | None,
    profile_id: UUID,
) -> list[Track]:
    """Resolve a playlist or smart playlist to its first MAX_TRACKS tracks.

    Validates ownership and returns tracks in the playlist's natural order
    (PlaylistTrack.position for static; the smart playlist's order_by for
    dynamic). Smart playlists exceeding MAX_TRACKS are truncated.
    """
    if source_playlist_id and source_smart_playlist_id:
        raise ValueError("Specify exactly one of source_playlist_id or source_smart_playlist_id")
    if not source_playlist_id and not source_smart_playlist_id:
        raise ValueError("Must specify a source playlist or smart playlist")

    if source_playlist_id:
        playlist = await db.get(Playlist, source_playlist_id)
        if not playlist or playlist.profile_id != profile_id:
            raise ValueError("Playlist not found")
        result = await db.execute(
            select(PlaylistTrack)
            .where(PlaylistTrack.playlist_id == source_playlist_id)
            .order_by(PlaylistTrack.position)
            .options(selectinload(PlaylistTrack.track))
            .limit(MAX_TRACKS)
        )
        tracks = [pt.track for pt in result.scalars().all() if pt.track is not None]
    else:
        service = SmartPlaylistService(db)
        smart = await service.get_by_id(source_smart_playlist_id, profile_id)  # type: ignore[arg-type]
        if not smart:
            raise ValueError("Smart playlist not found")
        tracks = await service.get_tracks(smart, limit=MAX_TRACKS, offset=0)

    if len(tracks) < MIN_TRACKS:
        raise ValueError(f"Need at least {MIN_TRACKS} tracks (got {len(tracks)})")

    return tracks


# ── Audio rendering ─────────────────────────────────────────────────────────


def _probe_duration(file_path: str) -> float:
    """Return duration in seconds via ffprobe."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path,
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {file_path}: {result.stderr.strip()}")
    return float(result.stdout.strip())


def _track_duration(track: Track) -> float:
    """Get track duration in seconds, falling back to ffprobe if missing."""
    if track.duration_seconds and track.duration_seconds > 0:
        return float(track.duration_seconds)
    if not track.file_path:
        raise RuntimeError(f"Track {track.id} has no file_path")
    return _probe_duration(track.file_path)


def _build_filter_graph(num_tracks: int, crossfade_seconds: int | None) -> str:
    """Build the -filter_complex string for the render."""
    # Normalize each input to 44.1kHz stereo float so the filters can chain cleanly.
    norm = [
        f"[{i}:a]aresample={TARGET_SAMPLE_RATE},"
        f"aformat=sample_fmts=fltp:channel_layouts=stereo[s{i}]"
        for i in range(num_tracks)
    ]

    if crossfade_seconds is None or crossfade_seconds <= 0:
        # Concat filter: needs all inputs in one shot.
        chain = "".join(f"[s{i}]" for i in range(num_tracks))
        chain += f"concat=n={num_tracks}:v=0:a=1[mix]"
        steps = norm + [chain, f"[mix]lowpass=f={LOW_PASS_HZ}[out]"]
        return ";".join(steps)

    # Crossfade chain: pairwise.
    cross_steps = []
    last_label = "s0"
    curve = DEFAULT_CROSSFADE_CURVE
    for i in range(1, num_tracks):
        out_label = f"a{i}" if i < num_tracks - 1 else "mix"
        cross_steps.append(
            f"[{last_label}][s{i}]"
            f"acrossfade=d={crossfade_seconds}:c1={curve}:c2={curve}[{out_label}]"
        )
        last_label = out_label
    steps = norm + cross_steps + [f"[mix]lowpass=f={LOW_PASS_HZ}[out]"]
    return ";".join(steps)


def _segment_offsets(durations: list[float], crossfade_seconds: int | None) -> list[float]:
    """Compute the start offset (seconds) of each track in the rendered file."""
    offsets: list[float] = []
    cursor = 0.0
    overlap = float(crossfade_seconds) if crossfade_seconds and crossfade_seconds > 0 else 0.0
    for i, dur in enumerate(durations):
        offsets.append(cursor)
        if i < len(durations) - 1:
            cursor += dur - overlap
    return offsets


def render_audio(
    tracks: list[Track],
    crossfade_seconds: int | None,
    output_path: Path,
) -> RenderResult:
    """Render the tracks to a single 128 kbps MP3 with optional crossfade.

    Single ffmpeg invocation: each input is normalized to 44.1 kHz stereo,
    chained via acrossfade or concat, low-passed at 15 kHz, encoded to MP3.
    """
    if not tracks:
        raise ValueError("No tracks to render")
    for t in tracks:
        if not t.file_path or not os.path.isfile(t.file_path):
            raise RuntimeError(f"Source file missing for track {t.id}: {t.file_path}")

    durations = [_track_duration(t) for t in tracks]
    filter_graph = _build_filter_graph(len(tracks), crossfade_seconds)

    cmd: list[str] = ["ffmpeg", "-y"]
    for t in tracks:
        cmd.extend(["-i", t.file_path])
    cmd.extend([
        "-filter_complex", filter_graph,
        "-map", "[out]",
        "-c:a", "libmp3lame",
        "-b:a", BITRATE,
        "-ar", str(TARGET_SAMPLE_RATE),
        "-ac", "2",
        str(output_path),
    ])

    logger.info("Rendering mixtape with %d tracks → %s", len(tracks), output_path)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if result.returncode != 0:
        # Surface the tail of stderr — ffmpeg writes useful errors at the end.
        tail = "\n".join(result.stderr.splitlines()[-20:])
        raise RuntimeError(f"ffmpeg render failed: {tail}")

    offsets = _segment_offsets(durations, crossfade_seconds)
    total = offsets[-1] + durations[-1] if offsets else 0.0
    return RenderResult(audio_path=output_path, segment_offsets=offsets, total_duration=total)


# ── Cover generation ────────────────────────────────────────────────────────


def _grid_dim_for(n: int) -> int:
    """Choose grid edge length so n tiles fit, preferring tighter packing."""
    if n <= 1:
        return 1
    if n <= 4:
        return 2
    if n <= 9:
        return 3
    return 4


def _fallback_tile(seed: str, size: int) -> Image.Image:
    """Generate a deterministic colored tile when artwork is missing."""
    h = hashlib.sha256(seed.encode()).digest()
    # Pleasant muted palette — pull hue from hash, fixed S/V.
    r, g, b = h[0], h[1], h[2]
    # Soften so fallback tiles don't scream against real art.
    r = 80 + (r % 100)
    g = 80 + (g % 100)
    b = 80 + (b % 100)
    return Image.new("RGB", (size, size), (r, g, b))


def _load_track_tile(track: Track, tile_size: int) -> Image.Image:
    """Load a square tile for a track from the album-art cache, or fallback."""
    album_key = album_key_for_track(track)
    art_path = get_artwork_path(album_key, size="full")
    if art_path.is_file():
        try:
            img = Image.open(art_path).convert("RGB")
            # Center-crop to square then resize.
            w, h = img.size
            edge = min(w, h)
            left = (w - edge) // 2
            top = (h - edge) // 2
            img = img.crop((left, top, left + edge, top + edge))
            return img.resize((tile_size, tile_size), Image.Resampling.LANCZOS)
        except Exception as e:  # pragma: no cover — defensive
            logger.warning("Failed to load artwork %s: %s", art_path, e)
    seed = f"{track.artist or ''}::{track.title or ''}::{track.id}"
    return _fallback_tile(seed, tile_size)


def _resolve_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Find a usable font, falling back to default if none of the candidates load."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in candidates:
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def generate_cover(
    tracks: list[Track],
    name: str,
    output_path: Path,
    byline: str | None = None,
) -> None:
    """Render a 1000×1000 JPEG: track-art collage + title band along the bottom.

    When ``byline`` is non-empty, a smaller "by <byline>" line is drawn
    beneath the title in the same band.
    """
    canvas = Image.new("RGB", (COVER_SIZE, COVER_SIZE), (16, 16, 16))
    grid = _grid_dim_for(len(tracks))
    tile_size = COVER_SIZE // grid

    for idx in range(grid * grid):
        if idx < len(tracks):
            tile = _load_track_tile(tracks[idx], tile_size)
        else:
            tile = _fallback_tile(f"empty-{idx}", tile_size)
        col = idx % grid
        row = idx // grid
        canvas.paste(tile, (col * tile_size, row * tile_size))

    # Bottom title band: 25% height, semi-translucent overlay.
    band_h = COVER_SIZE // 4
    band = Image.new("RGBA", (COVER_SIZE, band_h), (0, 0, 0, 200))
    canvas.paste(band, (0, COVER_SIZE - band_h), band)

    draw = ImageDraw.Draw(canvas)
    title_font_size = 72
    title_font = _resolve_font(title_font_size)
    # Crude fit: shrink title font down if too wide.
    while True:
        bbox = draw.textbbox((0, 0), name, font=title_font)
        if bbox[2] - bbox[0] <= COVER_SIZE - 80 or title_font_size <= 28:
            break
        title_font_size -= 6
        title_font = _resolve_font(title_font_size)
    title_bbox = draw.textbbox((0, 0), name, font=title_font)
    title_w = title_bbox[2] - title_bbox[0]
    title_h = title_bbox[3] - title_bbox[1]

    byline_text = f"by {byline}" if byline else None
    if byline_text:
        byline_font = _resolve_font(36)
        byline_bbox = draw.textbbox((0, 0), byline_text, font=byline_font)
        byline_w = byline_bbox[2] - byline_bbox[0]
        byline_h = byline_bbox[3] - byline_bbox[1]
        # Stack title + byline vertically within the band, centered as a block.
        gap = 12
        block_h = title_h + gap + byline_h
        block_top = COVER_SIZE - band_h + (band_h - block_h) // 2
        title_x = (COVER_SIZE - title_w) // 2
        title_y = block_top - 8
        byline_x = (COVER_SIZE - byline_w) // 2
        byline_y = block_top + title_h + gap - 8
        draw.text((title_x, title_y), name, fill=(255, 255, 255), font=title_font)
        draw.text((byline_x, byline_y), byline_text, fill=(220, 220, 220), font=byline_font)
    else:
        title_x = (COVER_SIZE - title_w) // 2
        title_y = COVER_SIZE - band_h + (band_h - title_h) // 2 - 8
        draw.text((title_x, title_y), name, fill=(255, 255, 255), font=title_font)

    canvas.save(output_path, "JPEG", quality=88)


# ── Tracklist + tag writing ─────────────────────────────────────────────────


def _format_timestamp(seconds: float) -> str:
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def write_tracklist(
    tracks: list[Track],
    name: str,
    segment_offsets: list[float],
    total_duration: float,
    output_path: Path,
    byline: str | None = None,
) -> None:
    """Write a human-readable tracklist text file."""
    lines = [
        name,
        f"Generated {datetime.now().strftime('%Y-%m-%d')} by Familiar",
    ]
    if byline:
        lines.append(f"Compiled by {byline}")
    lines.append("")
    for i, (track, offset) in enumerate(zip(tracks, segment_offsets, strict=True), start=1):
        artist = track.artist or "Unknown Artist"
        title = track.title or "Untitled"
        lines.append(f"{i:02d}. [{_format_timestamp(offset)}] {artist} — {title}")
    lines.append("")
    lines.append(f"Total duration: {_format_timestamp(total_duration)}")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def embed_tags(
    audio_path: Path,
    name: str,
    cover_path: Path,
    tracks: list[Track],
    segment_offsets: list[float],
    total_duration: float,
    byline: str | None = None,
) -> None:
    """Write ID3v2.4 tags, embed cover art, add CHAP markers per source track.

    When ``byline`` is non-empty, also write TPE2 (album artist — what
    most players display prominently) and TPE4 (interpreter/compiler —
    semantically the closest frame for "compiled by").
    """
    try:
        tags = ID3(audio_path)
    except ID3NoHeaderError:
        tags = ID3()

    tags.delall("TIT2")
    tags.delall("TPE1")
    tags.delall("TPE2")
    tags.delall("TPE4")
    tags.delall("TALB")
    tags.delall("TYER")
    tags.delall("TCON")
    tags.delall("APIC")
    tags.delall("CHAP")
    tags.delall("CTOC")

    tags.add(TIT2(encoding=3, text=[name]))
    tags.add(TPE1(encoding=3, text=["Various Artists"]))
    tags.add(TALB(encoding=3, text=[name]))
    tags.add(TYER(encoding=3, text=[str(datetime.now().year)]))
    tags.add(TCON(encoding=3, text=["Mixtape"]))
    if byline:
        tags.add(TPE2(encoding=3, text=[byline]))
        tags.add(TPE4(encoding=3, text=[byline]))

    cover_bytes = cover_path.read_bytes()
    tags.add(
        APIC(
            encoding=3,
            mime="image/jpeg",
            type=3,  # front cover
            desc="",
            data=cover_bytes,
        )
    )

    # CHAP markers — let podcast/audiobook-aware players skip between source tracks.
    chapter_ids = []
    for i, (track, offset) in enumerate(zip(tracks, segment_offsets, strict=True)):
        end = segment_offsets[i + 1] if i + 1 < len(segment_offsets) else total_duration
        chap_id = f"ch{i:02d}"
        chapter_ids.append(chap_id)
        chapter_title = f"{track.artist or 'Unknown'} — {track.title or 'Untitled'}"
        tags.add(
            CHAP(
                element_id=chap_id,
                start_time=int(offset * 1000),
                end_time=int(end * 1000),
                start_offset=0xFFFFFFFF,
                end_offset=0xFFFFFFFF,
                sub_frames=[TIT2(encoding=3, text=[chapter_title])],
            )
        )

    tags.add(
        CTOC(
            element_id="toc",
            flags=CTOCFlags.TOP_LEVEL | CTOCFlags.ORDERED,
            child_element_ids=chapter_ids,
            sub_frames=[TIT2(encoding=3, text=["Tracks"])],
        )
    )

    tags.save(audio_path, v2_version=4)


# ── Bundle ─────────────────────────────────────────────────────────────────


def _safe_name(name: str) -> str:
    """Sanitize for filenames inside the ZIP and the ZIP itself."""
    cleaned = "".join(c if c.isalnum() or c in " -_." else "_" for c in name).strip()
    return cleaned or "Mixtape"


def bundle_zip(
    audio: Path,
    cover: Path,
    tracklist: Path,
    name: str,
    output_path: Path,
) -> None:
    """Bundle the three artifacts into a single ZIP keyed by the mixtape name."""
    safe = _safe_name(name)
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_STORED) as zf:
        zf.write(audio, f"{safe}/{safe}.mp3")
        zf.write(cover, f"{safe}/cover.jpg")
        zf.write(tracklist, f"{safe}/tracklist.txt")


# ── Orchestrator ────────────────────────────────────────────────────────────


def _redis_key(mixtape_id: UUID) -> str:
    return f"familiar:mixtape_export:{mixtape_id}"


def _publish_progress(redis_client, mixtape_id: UUID, **fields) -> None:
    """Publish current phase + progress to Redis for frontend polling."""
    payload = json.dumps(fields)
    try:
        redis_client.set(_redis_key(mixtape_id), payload, ex=3600)
    except Exception as e:  # pragma: no cover — Redis is optional
        logger.warning("Failed to publish mixtape progress: %s", e)


async def run_mixtape_export(mixtape_id: UUID) -> None:
    """End-to-end orchestrator: walks the pipeline and updates state.

    Run from the BackgroundManager (asyncio.create_task). Does its own
    DB session — never receives one from the request scope.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.services.background import get_background_manager

    bg = get_background_manager()
    engine = create_async_engine(settings.database_url)
    # expire_on_commit=False so Track ORM objects loaded inside a session
    # remain usable after we commit and exit the session block — the render
    # step runs outside the session and accesses .file_path / .artist / etc.
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    workdir = settings.mixtapes_path / str(mixtape_id)
    workdir.mkdir(parents=True, exist_ok=True)
    audio_path = workdir / "audio.mp3"
    cover_path = workdir / "cover.jpg"
    tracklist_path = workdir / "tracklist.txt"
    bundle_path = workdir / "bundle.zip"

    _publish_progress(bg.redis, mixtape_id, status="rendering", phase="resolving_tracks", progress=5)

    try:
        async with session_factory() as db:
            mixtape = await db.get(MixTape, mixtape_id)
            if not mixtape:
                raise RuntimeError(f"MixTape {mixtape_id} not found")

            mixtape.status = "rendering"
            await db.commit()

            tracks = await resolve_tracks(
                db,
                mixtape.source_playlist_id,
                mixtape.source_smart_playlist_id,
                mixtape.profile_id,
            )
            # Freeze the snapshot.
            mixtape.track_ids = [str(t.id) for t in tracks]
            await db.commit()

            crossfade = mixtape.crossfade_seconds
            name = mixtape.name
            byline = mixtape.byline

        _publish_progress(bg.redis, mixtape_id, status="rendering", phase="rendering_audio", progress=20)
        result = await asyncio.to_thread(render_audio, tracks, crossfade, audio_path)

        _publish_progress(bg.redis, mixtape_id, status="rendering", phase="generating_cover", progress=70)
        await asyncio.to_thread(generate_cover, tracks, name, cover_path, byline)

        _publish_progress(bg.redis, mixtape_id, status="rendering", phase="writing_tracklist", progress=82)
        await asyncio.to_thread(
            write_tracklist,
            tracks,
            name,
            result.segment_offsets,
            result.total_duration,
            tracklist_path,
            byline,
        )

        _publish_progress(bg.redis, mixtape_id, status="rendering", phase="writing_tags", progress=88)
        await asyncio.to_thread(
            embed_tags,
            audio_path,
            name,
            cover_path,
            tracks,
            result.segment_offsets,
            result.total_duration,
            byline,
        )

        _publish_progress(bg.redis, mixtape_id, status="rendering", phase="bundling", progress=95)
        await asyncio.to_thread(bundle_zip, audio_path, cover_path, tracklist_path, name, bundle_path)

        async with session_factory() as db:
            mixtape = await db.get(MixTape, mixtape_id)
            if mixtape:
                mixtape.status = "ready"
                mixtape.audio_path = str(audio_path)
                mixtape.cover_path = str(cover_path)
                mixtape.tracklist_path = str(tracklist_path)
                mixtape.bundle_path = str(bundle_path)
                mixtape.duration_seconds = result.total_duration
                mixtape.file_size_bytes = bundle_path.stat().st_size
                mixtape.completed_at = utcnow()
                await db.commit()

        _publish_progress(bg.redis, mixtape_id, status="ready", phase="ready", progress=100)
        logger.info("Mixtape %s ready (%.1fs, %d tracks)", mixtape_id, result.total_duration, len(tracks))

    except Exception as exc:
        logger.exception("Mixtape %s render failed", mixtape_id)
        # Best-effort cleanup of partial artifacts.
        for p in (audio_path, cover_path, tracklist_path, bundle_path):
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
        try:
            async with session_factory() as db:
                mixtape = await db.get(MixTape, mixtape_id)
                if mixtape:
                    mixtape.status = "failed"
                    mixtape.error_message = str(exc)[:500]
                    await db.commit()
        finally:
            _publish_progress(
                bg.redis, mixtape_id, status="failed", phase="failed", progress=0, error=str(exc)[:500]
            )
    finally:
        await engine.dispose()
