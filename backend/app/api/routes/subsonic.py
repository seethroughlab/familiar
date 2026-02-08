"""Subsonic-compatible REST API.

Implements the Subsonic API (http://www.subsonic.org/pages/api.jsp) to allow
native Subsonic clients (Symfonium, play:Sub, Amperfy, etc.) to browse,
search, and stream from Familiar.

Phase 1: browse, search, stream, artwork.
"""

import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Annotated
from uuid import UUID

import bcrypt as _bcrypt
from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession, get_db
from app.api.streaming import stream_file
from app.db.models import Profile, SubsonicCredential, Track, TrackStatus
from app.services.artwork import compute_album_hash, get_artwork_path

router = APIRouter(tags=["subsonic"])

SUBSONIC_API_VERSION = "1.16.1"
SUBSONIC_SERVER_NAME = "Familiar"

# MIME types for audio formats
AUDIO_MIME_TYPES = {
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
}


def _get_audio_mime_type(file_path: Path) -> str:
    return AUDIO_MIME_TYPES.get(file_path.suffix.lower(), "application/octet-stream")


# ---------------------------------------------------------------------------
# ID Mapping
# ---------------------------------------------------------------------------

def artist_id(name: str) -> str:
    """Stable deterministic ID for an artist name."""
    return "ar-" + hashlib.md5(name.lower().strip().encode()).hexdigest()[:16]


def album_id(album_artist: str, album: str) -> str:
    """Stable deterministic ID for an (album_artist, album) pair."""
    key = f"{(album_artist or '').lower().strip()}|{(album or '').lower().strip()}"
    return "al-" + hashlib.md5(key.encode()).hexdigest()[:16]


def parse_id(id_str: str) -> tuple[str, str]:
    """Parse a Subsonic ID back into (type, raw_id)."""
    if id_str.startswith("ar-"):
        return ("artist", id_str)
    elif id_str.startswith("al-"):
        return ("album", id_str)
    else:
        return ("track", id_str)


async def resolve_artist_name(db: AsyncSession, art_id: str) -> str | None:
    """Reverse-lookup: find the artist name whose hash matches *art_id*."""
    from sqlalchemy import func as sa_func

    result = await db.execute(
        select(sa_func.max(Track.artist).label("name"))
        .where(Track.artist.isnot(None), Track.artist != "", Track.status == TrackStatus.ACTIVE)
        .group_by(sa_func.lower(sa_func.trim(Track.artist)))
    )
    for (name,) in result.all():
        if artist_id(name) == art_id:
            return name
    return None


async def resolve_album(db: AsyncSession, al_id: str) -> tuple[str, str] | None:
    """Reverse-lookup: find (album_artist, album) whose hash matches *al_id*."""
    from sqlalchemy import func as sa_func

    album_artist_col = sa_func.coalesce(sa_func.nullif(Track.album_artist, ""), Track.artist)
    result = await db.execute(
        select(
            sa_func.max(album_artist_col).label("artist"),
            sa_func.max(Track.album).label("album"),
        )
        .where(Track.album.isnot(None), Track.album != "", Track.status == TrackStatus.ACTIVE)
        .group_by(sa_func.lower(album_artist_col), sa_func.lower(Track.album))
    )
    for row in result.all():
        if album_id(row.artist or "", row.album or "") == al_id:
            return (row.artist or "", row.album or "")
    return None


# ---------------------------------------------------------------------------
# Response Formatting
# ---------------------------------------------------------------------------

def subsonic_response(data: dict | None, fmt: str = "xml") -> Response:
    """Wrap data in a Subsonic response envelope."""
    if fmt == "json":
        body = {
            "subsonic-response": {
                "status": "ok",
                "version": SUBSONIC_API_VERSION,
                **(data or {}),
            }
        }
        import json
        return Response(
            content=json.dumps(body),
            media_type="application/json; charset=utf-8",
        )

    root = ET.Element("subsonic-response", {
        "xmlns": "http://subsonic.org/restapi",
        "status": "ok",
        "version": SUBSONIC_API_VERSION,
    })
    if data:
        _dict_to_xml(root, data)
    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")
    return Response(content=xml_str, media_type="text/xml; charset=utf-8")


def subsonic_error(code: int, message: str, fmt: str = "xml") -> Response:
    """Return a Subsonic error response."""
    if fmt == "json":
        import json
        body = {
            "subsonic-response": {
                "status": "failed",
                "version": SUBSONIC_API_VERSION,
                "error": {"code": code, "message": message},
            }
        }
        return Response(
            content=json.dumps(body),
            media_type="application/json; charset=utf-8",
        )

    root = ET.Element("subsonic-response", {
        "xmlns": "http://subsonic.org/restapi",
        "status": "failed",
        "version": SUBSONIC_API_VERSION,
    })
    ET.SubElement(root, "error", {"code": str(code), "message": message})
    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")
    return Response(content=xml_str, media_type="text/xml; charset=utf-8")


def _dict_to_xml(parent: ET.Element, data: dict) -> None:
    """Convert dict to Subsonic XML structure.

    Rules:
    - Scalar values -> attributes on parent
    - List values -> repeated child elements
    - Dict values -> child element with recursive conversion
    """
    for key, value in data.items():
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    child = ET.SubElement(parent, key)
                    _dict_to_xml(child, item)
                else:
                    child = ET.SubElement(parent, key)
                    child.text = str(item)
        elif isinstance(value, dict):
            child = ET.SubElement(parent, key)
            _dict_to_xml(child, value)
        elif value is not None:
            parent.set(key, str(value).lower() if isinstance(value, bool) else str(value))


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

class SubsonicAuthError(Exception):
    def __init__(self, code: int, message: str, fmt: str = "xml"):
        self.code = code
        self.message = message
        self.fmt = fmt


async def authenticate_subsonic(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Profile:
    """Validate Subsonic auth params and return the associated Profile."""
    # Subsonic sends params as query params for both GET and POST
    params = dict(request.query_params)
    # Some clients send form-encoded POST body
    if request.method == "POST":
        body = await request.form()
        for k, v in body.items():
            if k not in params:
                params[k] = v

    username = params.get("u")
    password = params.get("p")
    token = params.get("t")
    salt = params.get("s")
    fmt = params.get("f", "xml")

    if not username:
        raise SubsonicAuthError(10, "Missing required parameter: u", fmt)

    result = await db.execute(
        select(SubsonicCredential)
        .where(SubsonicCredential.username == username)
        .options(selectinload(SubsonicCredential.profile))
    )
    cred = result.scalar_one_or_none()
    if not cred:
        raise SubsonicAuthError(40, "Wrong username or password", fmt)

    if token and salt:
        # Token auth: client sends t=md5(password+salt), s=salt
        expected = hashlib.md5((cred.password_token + salt).encode()).hexdigest()
        if token.lower() != expected.lower():
            raise SubsonicAuthError(40, "Wrong username or password", fmt)
    elif password:
        # Password auth: p=plaintext or p=enc:hex-encoded
        if password.startswith("enc:"):
            password = bytes.fromhex(password[4:]).decode("utf-8")
        if not _bcrypt.checkpw(password.encode(), cred.password_hash.encode()):
            raise SubsonicAuthError(40, "Wrong username or password", fmt)
    else:
        raise SubsonicAuthError(10, "Missing authentication parameters", fmt)

    return cred.profile


SubsonicProfile = Annotated[Profile, Depends(authenticate_subsonic)]


def _get_format(request: Request) -> str:
    """Get response format from request params."""
    return request.query_params.get("f", "xml")


# ---------------------------------------------------------------------------
# Track Serializer
# ---------------------------------------------------------------------------

def track_to_child(track: Track, parent_id: str | None = None) -> dict:
    """Convert a Track model to Subsonic child/song dict."""
    art_name = track.album_artist or track.artist or ""
    alb_name = track.album or ""
    al_id = album_id(art_name, alb_name) if alb_name else None

    d: dict = {
        "id": str(track.id),
        "parent": parent_id or al_id or "",
        "isDir": "false",
        "title": track.title or "Unknown",
        "album": track.album or "",
        "artist": track.artist or "",
    }
    if track.track_number:
        d["track"] = str(track.track_number)
    if track.year:
        d["year"] = str(track.year)
    if track.genre:
        d["genre"] = track.genre
    if al_id:
        d["coverArt"] = al_id
    if track.file_size:
        d["size"] = str(track.file_size)

    fp = Path(track.file_path)
    d["contentType"] = _get_audio_mime_type(fp)
    d["suffix"] = fp.suffix.lstrip(".")
    if track.duration_seconds:
        d["duration"] = str(int(track.duration_seconds))
    if track.bitrate:
        d["bitRate"] = str(track.bitrate // 1000)
    d["isVideo"] = "false"
    d["type"] = "music"
    if track.created_at:
        d["created"] = track.created_at.isoformat()
    if al_id:
        d["albumId"] = al_id
    if track.artist:
        d["artistId"] = artist_id(track.artist)

    return d


# ---------------------------------------------------------------------------
# System Endpoints
# ---------------------------------------------------------------------------

@router.get("/ping.view")
@router.get("/ping")
@router.post("/ping.view")
@router.post("/ping")
async def ping(request: Request, profile: SubsonicProfile):
    return subsonic_response(None, _get_format(request))


@router.get("/getLicense.view")
@router.get("/getLicense")
async def get_license(request: Request, profile: SubsonicProfile):
    return subsonic_response({
        "license": {
            "valid": "true",
            "email": "",
            "licenseExpires": "2099-12-31T00:00:00",
        }
    }, _get_format(request))


# ---------------------------------------------------------------------------
# Browsing Endpoints
# ---------------------------------------------------------------------------

@router.get("/getMusicFolders.view")
@router.get("/getMusicFolders")
async def get_music_folders(request: Request, profile: SubsonicProfile):
    from app.config import MUSIC_LIBRARY_PATH
    from app.services.app_settings import get_app_settings_service

    paths = list(get_app_settings_service().get().music_library_paths)
    if MUSIC_LIBRARY_PATH and str(MUSIC_LIBRARY_PATH) not in paths:
        paths = [str(MUSIC_LIBRARY_PATH)] + paths

    folders = [
        {"id": str(i + 1), "name": Path(p).name}
        for i, p in enumerate(paths)
    ]
    return subsonic_response({"musicFolders": {"musicFolder": folders}}, _get_format(request))


@router.get("/getArtists.view")
@router.get("/getArtists")
async def get_artists(request: Request, db: DbSession, profile: SubsonicProfile):
    """Return all artists grouped by first letter (ID3-based)."""
    from sqlalchemy import func as sa_func

    result = await db.execute(
        select(
            sa_func.max(Track.artist).label("name"),
            sa_func.count(Track.id.distinct()).label("album_count"),
        )
        .where(Track.artist.isnot(None), Track.artist != "", Track.status == TrackStatus.ACTIVE)
        .group_by(sa_func.lower(sa_func.trim(Track.artist)))
        .order_by(sa_func.lower(sa_func.trim(Track.artist)))
    )

    indexes: dict[str, list] = {}
    for row in result.all():
        letter = (row.name[0] if row.name else "#").upper()
        if not letter.isalpha():
            letter = "#"
        indexes.setdefault(letter, []).append({
            "id": artist_id(row.name),
            "name": row.name,
            "albumCount": str(row.album_count),
        })

    index_list = [
        {"name": letter, "artist": artists}
        for letter, artists in sorted(indexes.items())
    ]
    return subsonic_response({"artists": {"index": index_list}}, _get_format(request))


@router.get("/getIndexes.view")
@router.get("/getIndexes")
async def get_indexes(request: Request, db: DbSession, profile: SubsonicProfile):
    """Return artist index (folder-based variant). Maps to same data as getArtists."""
    return await get_artists(request, db, profile)


@router.get("/getArtist.view")
@router.get("/getArtist")
async def get_artist(request: Request, db: DbSession, profile: SubsonicProfile, id: str):
    """Return artist detail with album list."""
    from sqlalchemy import func as sa_func

    fmt = _get_format(request)
    name = await resolve_artist_name(db, id)
    if not name:
        return subsonic_error(70, "Artist not found", fmt)

    album_artist_col = sa_func.coalesce(sa_func.nullif(Track.album_artist, ""), Track.artist)
    albums_result = await db.execute(
        select(
            sa_func.max(Track.album).label("name"),
            sa_func.max(album_artist_col).label("artist"),
            sa_func.max(Track.year).label("year"),
            sa_func.count(Track.id).label("song_count"),
            sa_func.sum(Track.duration_seconds).label("duration"),
        )
        .where(
            sa_func.lower(sa_func.trim(Track.artist)) == name.lower().strip(),
            Track.status == TrackStatus.ACTIVE,
            Track.album.isnot(None), Track.album != "",
        )
        .group_by(sa_func.lower(Track.album))
        .order_by(sa_func.max(Track.year).desc().nullslast())
    )

    albums = []
    for row in albums_result.all():
        al_id = album_id(row.artist or name, row.name)
        albums.append({
            "id": al_id,
            "name": row.name,
            "artist": row.artist or name,
            "artistId": id,
            "songCount": str(row.song_count),
            "duration": str(int(row.duration or 0)),
            "coverArt": al_id,
            **({"year": str(row.year)} if row.year else {}),
        })

    artist_data = {
        "id": id,
        "name": name,
        "albumCount": str(len(albums)),
        "album": albums,
    }
    return subsonic_response({"artist": artist_data}, fmt)


@router.get("/getAlbum.view")
@router.get("/getAlbum")
async def get_album(request: Request, db: DbSession, profile: SubsonicProfile, id: str):
    """Return album detail with track list."""
    from sqlalchemy import func as sa_func

    fmt = _get_format(request)
    album_info = await resolve_album(db, id)
    if not album_info:
        return subsonic_error(70, "Album not found", fmt)

    artist_name, album_name = album_info

    album_artist_col = sa_func.coalesce(sa_func.nullif(Track.album_artist, ""), Track.artist)
    tracks_result = await db.execute(
        select(Track)
        .where(
            sa_func.lower(album_artist_col) == artist_name.lower(),
            sa_func.lower(Track.album) == album_name.lower(),
            Track.status == TrackStatus.ACTIVE,
        )
        .order_by(Track.disc_number, Track.track_number, Track.title)
    )
    tracks = tracks_result.scalars().all()

    songs = [track_to_child(t, id) for t in tracks]
    art_id_str = artist_id(artist_name)

    album_data = {
        "id": id,
        "name": album_name,
        "artist": artist_name,
        "artistId": art_id_str,
        "songCount": str(len(songs)),
        "duration": str(int(sum(t.duration_seconds or 0 for t in tracks))),
        "coverArt": id,
        "song": songs,
    }
    if tracks and tracks[0].year:
        album_data["year"] = str(tracks[0].year)
    return subsonic_response({"album": album_data}, fmt)


@router.get("/getSong.view")
@router.get("/getSong")
async def get_song(request: Request, db: DbSession, profile: SubsonicProfile, id: str):
    """Return a single song."""
    fmt = _get_format(request)
    try:
        track = await db.get(Track, UUID(id))
    except ValueError:
        return subsonic_error(70, "Song not found", fmt)
    if not track:
        return subsonic_error(70, "Song not found", fmt)
    return subsonic_response({"song": track_to_child(track)}, fmt)


@router.get("/getAlbumList2.view")
@router.get("/getAlbumList2")
async def get_album_list2(
    request: Request, db: DbSession, profile: SubsonicProfile,
    type: str = "newest",
    size: int = 10,
    offset: int = 0,
):
    """Return album list (ID3-based). Supports newest, random, alphabeticalByName."""
    from sqlalchemy import func as sa_func

    fmt = _get_format(request)
    size = min(size, 500)

    album_artist_col = sa_func.coalesce(sa_func.nullif(Track.album_artist, ""), Track.artist)
    base = (
        select(
            sa_func.max(Track.album).label("name"),
            sa_func.max(album_artist_col).label("artist"),
            sa_func.max(Track.year).label("year"),
            sa_func.count(Track.id).label("song_count"),
            sa_func.sum(Track.duration_seconds).label("duration"),
            sa_func.max(Track.created_at).label("created"),
        )
        .where(Track.album.isnot(None), Track.album != "", Track.status == TrackStatus.ACTIVE)
        .group_by(sa_func.lower(album_artist_col), sa_func.lower(Track.album))
    )

    if type == "newest":
        base = base.order_by(sa_func.max(Track.created_at).desc().nullslast())
    elif type == "alphabeticalByName":
        base = base.order_by(sa_func.lower(sa_func.max(Track.album)))
    elif type == "alphabeticalByArtist":
        base = base.order_by(sa_func.lower(sa_func.max(album_artist_col)))
    elif type == "random":
        base = base.order_by(sa_func.random())
    else:
        base = base.order_by(sa_func.max(Track.created_at).desc().nullslast())

    result = await db.execute(base.offset(offset).limit(size))

    albums = []
    for row in result.all():
        al_id = album_id(row.artist or "", row.name)
        albums.append({
            "id": al_id,
            "name": row.name,
            "artist": row.artist or "",
            "artistId": artist_id(row.artist or ""),
            "songCount": str(row.song_count),
            "duration": str(int(row.duration or 0)),
            "coverArt": al_id,
            **({"year": str(row.year)} if row.year else {}),
            **({"created": row.created.isoformat()} if row.created else {}),
        })

    return subsonic_response({"albumList2": {"album": albums}}, fmt)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

@router.get("/search3.view")
@router.get("/search3")
async def search3(
    request: Request, db: DbSession, profile: SubsonicProfile,
    query: str = "",
    artistCount: int = 20, artistOffset: int = 0,
    albumCount: int = 20, albumOffset: int = 0,
    songCount: int = 20, songOffset: int = 0,
):
    """Unified search across artists, albums, songs."""
    from sqlalchemy import func as sa_func

    fmt = _get_format(request)
    search_filter = f"%{query}%"

    # Artists
    artist_results = await db.execute(
        select(sa_func.max(Track.artist).label("name"))
        .where(Track.artist.ilike(search_filter), Track.status == TrackStatus.ACTIVE)
        .group_by(sa_func.lower(Track.artist))
        .offset(artistOffset).limit(artistCount)
    )
    artists = [
        {"id": artist_id(r.name), "name": r.name}
        for r in artist_results.all()
    ]

    # Albums
    album_artist_col = sa_func.coalesce(sa_func.nullif(Track.album_artist, ""), Track.artist)
    album_results = await db.execute(
        select(
            sa_func.max(Track.album).label("name"),
            sa_func.max(album_artist_col).label("artist"),
            sa_func.count(Track.id).label("song_count"),
        )
        .where(Track.album.ilike(search_filter), Track.status == TrackStatus.ACTIVE)
        .group_by(sa_func.lower(album_artist_col), sa_func.lower(Track.album))
        .offset(albumOffset).limit(albumCount)
    )
    albums = [
        {
            "id": album_id(r.artist or "", r.name),
            "name": r.name,
            "artist": r.artist or "",
            "artistId": artist_id(r.artist or ""),
            "coverArt": album_id(r.artist or "", r.name),
        }
        for r in album_results.all()
    ]

    # Songs
    song_results = await db.execute(
        select(Track)
        .where(
            (Track.title.ilike(search_filter) | Track.artist.ilike(search_filter)),
            Track.status == TrackStatus.ACTIVE,
        )
        .order_by(Track.title)
        .offset(songOffset).limit(songCount)
    )
    songs = [track_to_child(t) for t in song_results.scalars().all()]

    return subsonic_response({
        "searchResult3": {"artist": artists, "album": albums, "song": songs}
    }, fmt)


@router.get("/search2.view")
@router.get("/search2")
async def search2(
    request: Request, db: DbSession, profile: SubsonicProfile,
    query: str = "",
    artistCount: int = 20, artistOffset: int = 0,
    albumCount: int = 20, albumOffset: int = 0,
    songCount: int = 20, songOffset: int = 0,
):
    """Older search variant — delegates to search3."""
    return await search3(
        request, db, profile, query,
        artistCount, artistOffset,
        albumCount, albumOffset,
        songCount, songOffset,
    )


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------

@router.get("/stream.view")
@router.get("/stream")
async def stream(
    request: Request, db: DbSession, profile: SubsonicProfile,
    id: str,
):
    """Stream audio file. Phase 1: direct file serving (no transcoding)."""
    fmt = _get_format(request)
    try:
        track = await db.get(Track, UUID(id))
    except ValueError:
        return subsonic_error(70, "Song not found", fmt)

    if not track:
        return subsonic_error(70, "Song not found", fmt)

    file_path = Path(track.file_path)
    if not file_path.exists():
        return subsonic_error(70, "File not found", fmt)

    mime_type = _get_audio_mime_type(file_path)
    return await stream_file(file_path, request, mime_type)


@router.get("/download.view")
@router.get("/download")
async def download(
    request: Request, db: DbSession, profile: SubsonicProfile,
    id: str,
):
    """Download a song file. Same as stream for Phase 1."""
    return await stream(request, db, profile, id)


# ---------------------------------------------------------------------------
# Artwork
# ---------------------------------------------------------------------------

@router.get("/getCoverArt.view")
@router.get("/getCoverArt")
async def get_cover_art(
    request: Request, db: DbSession, profile: SubsonicProfile,
    id: str,
    size: int | None = None,
):
    """Return album artwork."""
    fmt = _get_format(request)
    id_type, _ = parse_id(id)
    album_hash: str | None = None

    if id_type == "album":
        album_info = await resolve_album(db, id)
        if album_info:
            album_hash = compute_album_hash(album_info[0], album_info[1])
    elif id_type == "track":
        try:
            track = await db.get(Track, UUID(id))
        except ValueError:
            track = None
        if track:
            album_hash = compute_album_hash(track.artist or "", track.album or "")
    else:
        # Could be an artist ID or unknown — try track UUID
        try:
            track = await db.get(Track, UUID(id))
            if track:
                album_hash = compute_album_hash(track.artist or "", track.album or "")
        except ValueError:
            pass

    if not album_hash:
        return subsonic_error(70, "Cover art not found", fmt)

    art_size = "thumb" if size and size <= 300 else "full"
    art_path = get_artwork_path(album_hash, art_size)

    if not art_path.exists():
        art_path = get_artwork_path(album_hash, "full")

    if not art_path.exists():
        return subsonic_error(70, "Cover art not found", fmt)

    return FileResponse(art_path, media_type="image/jpeg")


# ---------------------------------------------------------------------------
# Stubs for unimplemented endpoints (return empty to avoid client errors)
# ---------------------------------------------------------------------------

@router.get("/getStarred2.view")
@router.get("/getStarred2")
@router.get("/getStarred.view")
@router.get("/getStarred")
async def get_starred(request: Request, profile: SubsonicProfile):
    return subsonic_response({"starred2": {}}, _get_format(request))


@router.get("/getPlaylists.view")
@router.get("/getPlaylists")
async def get_playlists(request: Request, profile: SubsonicProfile):
    return subsonic_response({"playlists": {}}, _get_format(request))


@router.get("/getUser.view")
@router.get("/getUser")
async def get_user(request: Request, profile: SubsonicProfile, username: str = ""):
    return subsonic_response({
        "user": {
            "username": username or "familiar",
            "email": "",
            "scrobblingEnabled": "false",
            "adminRole": "false",
            "settingsRole": "false",
            "downloadRole": "true",
            "uploadRole": "false",
            "playlistRole": "true",
            "coverArtRole": "true",
            "commentRole": "false",
            "podcastRole": "false",
            "streamRole": "true",
            "jukeboxRole": "false",
            "shareRole": "false",
            "videoConversionRole": "false",
            "folder": ["1"],
        }
    }, _get_format(request))


@router.get("/scrobble.view")
@router.get("/scrobble")
@router.post("/scrobble.view")
@router.post("/scrobble")
async def scrobble(request: Request, profile: SubsonicProfile):
    """Accept scrobble requests silently (Phase 2)."""
    return subsonic_response(None, _get_format(request))


@router.get("/getRandomSongs.view")
@router.get("/getRandomSongs")
async def get_random_songs(
    request: Request, db: DbSession, profile: SubsonicProfile,
    size: int = 10,
):
    """Return random songs."""
    from sqlalchemy import func as sa_func

    fmt = _get_format(request)
    size = min(size, 500)

    result = await db.execute(
        select(Track)
        .where(Track.status == TrackStatus.ACTIVE)
        .order_by(sa_func.random())
        .limit(size)
    )
    tracks = result.scalars().all()
    songs = [track_to_child(t) for t in tracks]
    return subsonic_response({"randomSongs": {"song": songs}}, fmt)


@router.get("/getGenres.view")
@router.get("/getGenres")
async def get_genres(request: Request, db: DbSession, profile: SubsonicProfile):
    """Return all genres with song/album counts."""
    from sqlalchemy import func as sa_func

    fmt = _get_format(request)
    result = await db.execute(
        select(
            Track.genre,
            sa_func.count(Track.id).label("song_count"),
            sa_func.count(sa_func.distinct(sa_func.lower(Track.album))).label("album_count"),
        )
        .where(Track.genre.isnot(None), Track.genre != "", Track.status == TrackStatus.ACTIVE)
        .group_by(Track.genre)
        .order_by(Track.genre)
    )

    genres = [
        {"songCount": str(r.song_count), "albumCount": str(r.album_count), "value": r.genre}
        for r in result.all()
    ]
    return subsonic_response({"genres": {"genre": genres}}, fmt)
