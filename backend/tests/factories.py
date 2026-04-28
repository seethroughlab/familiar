"""Factory functions for creating test objects with sensible defaults.

Includes both dict-based factories (for API-level tests) and async DB-insert
factories (for integration tests that need real ORM objects in PostgreSQL).

Usage (API-level):
    track = create_test_track(client, test_profile)
    playlist = create_test_playlist(client, test_profile, track_ids=[track["id"]])

Usage (DB-level):
    track = await insert_test_track(async_db, title="My Song")
    analysis = await insert_test_analysis(async_db, track.id, {"energy": 0.8})  # sets typed column
"""

from datetime import datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ChangeScope,
    ChangeSource,
    ChangeStatus,
    Playlist,
    PlaylistTrack,
    Profile,
    ProfilePlayHistory,
    ProposedChange,
    SmartPlaylist,
    Track,
    TrackAnalysis,
)
from app.utils.time import utcnow
from tests.conftest import make_profile_headers

# ---------------------------------------------------------------------------
# API-level factories (dict-based, for route tests using TestClient)
# ---------------------------------------------------------------------------


def create_test_track(
    client: TestClient,
    profile: dict,
    *,
    title: str = "Test Track",
    artist: str = "Test Artist",
    album: str = "Test Album",
    genre: str = "Electronic",
    year: int = 2024,
    duration_seconds: float = 180.0,
    file_path: str | None = None,
) -> dict:
    """Create a track data dict (not inserted into DB via API)."""
    return {
        "id": str(uuid4()),
        "title": title,
        "artist": artist,
        "album": album,
        "genre": genre,
        "year": year,
        "duration_seconds": duration_seconds,
        "file_path": file_path or f"/music/{artist}/{album}/{title}.mp3",
    }


def create_test_playlist(
    client: TestClient,
    profile: dict,
    *,
    name: str = "Test Playlist",
    description: str | None = None,
    track_ids: list[str] | None = None,
) -> dict:
    """Create a playlist via the API and return its data."""
    headers = make_profile_headers(profile)
    response = client.post(
        "/api/v1/playlists",
        json={"name": name, "description": description},
        headers=headers,
    )
    assert response.status_code == 201, f"Failed to create playlist: {response.text}"
    playlist = response.json()

    if track_ids:
        for track_id in track_ids:
            client.post(
                f"/api/v1/playlists/{playlist['id']}/tracks",
                json={"track_id": track_id},
                headers=headers,
            )

    return playlist


def create_test_smart_playlist(
    client: TestClient,
    profile: dict,
    *,
    name: str = "Test Smart Playlist",
    rules: list[dict] | None = None,
    match_mode: str = "all",
    order_by: str = "title",
    max_tracks: int | None = None,
) -> dict:
    """Create a smart playlist via the API and return its data."""
    headers = make_profile_headers(profile)
    body: dict = {
        "name": name,
        "rules": rules or [{"field": "genre", "operator": "contains", "value": "rock"}],
        "match_mode": match_mode,
        "order_by": order_by,
    }
    if max_tracks is not None:
        body["max_tracks"] = max_tracks

    response = client.post(
        "/api/v1/smart-playlists",
        json=body,
        headers=headers,
    )
    assert response.status_code == 201, f"Failed to create smart playlist: {response.text}"
    return response.json()


# ---------------------------------------------------------------------------
# Async DB-insert factories (for integration tests using async_db fixture)
# ---------------------------------------------------------------------------


async def insert_test_profile(
    db: AsyncSession,
    *,
    name: str = "Test Profile",
) -> Profile:
    """Insert a Profile into the database and return it."""
    profile = Profile(name=name)
    db.add(profile)
    await db.flush()
    return profile


async def insert_test_track(
    db: AsyncSession,
    *,
    title: str = "Test Track",
    artist: str = "Test Artist",
    album: str = "Test Album",
    album_artist: str | None = None,
    genre: str | None = "Electronic",
    year: int | None = 2024,
    duration_seconds: float | None = 180.0,
    file_path: str | None = None,
    file_hash: str | None = None,
    isrc: str | None = None,
    format: str | None = "mp3",
    resolve_canonical: bool = True,
) -> Track:
    """Insert a Track into the database and return it (flushed, not committed).

    By default also resolves the artist tag to a canonical ``Artist`` row
    via the same resolver the scanner uses, registers an ``ArtistAlias``,
    and sets ``track.canonical_artist_id``. When ``album_artist`` is
    passed, ``canonical_album_artist_id`` is populated the same way
    (Pass 3 dual-write).
    """
    track = Track(
        file_path=file_path or f"/test/music/{uuid4().hex[:12]}.mp3",
        file_hash=file_hash or uuid4().hex,
        title=title,
        artist=artist,
        album=album,
        album_artist=album_artist,
        genre=genre,
        year=year,
        duration_seconds=duration_seconds,
        isrc=isrc,
        format=format,
    )
    db.add(track)
    await db.flush()

    if resolve_canonical:
        from app.services.artist_resolver import resolve_canonical_artist

        if artist:
            canonical = await resolve_canonical_artist(
                db, artist, do_mb_lookup=False, create_if_missing=True
            )
            if canonical is not None:
                track.canonical_artist_id = canonical.id
        if album_artist:
            album_canonical = await resolve_canonical_artist(
                db, album_artist, do_mb_lookup=False, create_if_missing=True
            )
            if album_canonical is not None:
                track.canonical_album_artist_id = album_canonical.id
        await db.flush()

    return track


async def insert_test_analysis(
    db: AsyncSession,
    track_id: UUID,
    features: dict | None = None,
    *,
    features_version: int = 1,
) -> TrackAnalysis:
    """Insert a TrackAnalysis row for a track.

    The `features` dict maps typed column names to values (e.g. {"energy": 0.8}).
    """
    analysis = TrackAnalysis(
        track_id=track_id,
        features_version=features_version,
    )
    if features:
        for col_name, value in features.items():
            setattr(analysis, col_name, value)
    db.add(analysis)
    await db.flush()
    return analysis


async def insert_test_play_history(
    db: AsyncSession,
    profile_id: UUID,
    track_id: UUID,
    *,
    play_count: int = 1,
    last_played_at: datetime | None = None,
    total_play_seconds: float = 180.0,
) -> ProfilePlayHistory:
    """Insert a ProfilePlayHistory row."""
    history = ProfilePlayHistory(
        profile_id=profile_id,
        track_id=track_id,
        play_count=play_count,
        last_played_at=last_played_at or utcnow(),
        total_play_seconds=total_play_seconds,
    )
    db.add(history)
    await db.flush()
    return history


async def insert_test_proposed_change(
    db: AsyncSession,
    target_ids: list[str],
    *,
    change_type: str = "metadata",
    target_type: str = "track",
    field: str = "genre",
    old_value: str | dict | None = None,
    new_value: str | dict = "New Genre",
    source: ChangeSource = ChangeSource.USER_REQUEST,
    status: ChangeStatus = ChangeStatus.PENDING,
    scope: ChangeScope = ChangeScope.DB_ONLY,
    confidence: float = 1.0,
) -> ProposedChange:
    """Insert a ProposedChange and return it."""
    change = ProposedChange(
        change_type=change_type,
        target_type=target_type,
        target_ids=target_ids,
        field=field,
        old_value=old_value,
        new_value=new_value,
        source=source,
        status=status,
        scope=scope,
        confidence=confidence,
    )
    db.add(change)
    await db.flush()
    return change


async def insert_test_playlist(
    db: AsyncSession,
    profile_id: UUID,
    *,
    name: str = "Test Playlist",
    is_auto_generated: bool = False,
) -> Playlist:
    """Insert a Playlist and return it."""
    playlist = Playlist(
        profile_id=profile_id,
        name=name,
        is_auto_generated=is_auto_generated,
    )
    db.add(playlist)
    await db.flush()
    return playlist


async def insert_test_playlist_track(
    db: AsyncSession,
    playlist_id: UUID,
    *,
    track_id: UUID,
    position: int = 0,
) -> PlaylistTrack:
    """Insert a PlaylistTrack junction row."""
    pt = PlaylistTrack(
        playlist_id=playlist_id,
        track_id=track_id,
        position=position,
    )
    db.add(pt)
    await db.flush()
    return pt


async def insert_test_smart_playlist(
    db: AsyncSession,
    profile_id: UUID,
    *,
    name: str = "Test Smart Playlist",
    rules: list[dict] | None = None,
    match_mode: str = "all",
    order_by: str = "title",
    order_direction: str = "asc",
    max_tracks: int | None = None,
) -> SmartPlaylist:
    """Insert a SmartPlaylist and return it."""
    sp = SmartPlaylist(
        profile_id=profile_id,
        name=name,
        rules=rules or [{"field": "genre", "operator": "contains", "value": "rock"}],
        match_mode=match_mode,
        order_by=order_by,
        order_direction=order_direction,
        max_tracks=max_tracks,
    )
    db.add(sp)
    await db.flush()
    return sp
