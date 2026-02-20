"""MusicBrainz enrichment service for track metadata."""

import logging
from typing import Any

import musicbrainzngs

logger = logging.getLogger(__name__)

# Configure the MusicBrainz client
musicbrainzngs.set_useragent(
    "Familiar",
    "0.1.0",
    "https://github.com/familiar-music/familiar",
)

# Rate limiting: MusicBrainz allows 1 request per second
musicbrainzngs.set_rate_limit(limit_or_interval=1.0)


def _normalize_for_comparison(s: str | None) -> str:
    """Normalize a string for comparison (lowercase, stripped)."""
    if not s:
        return ""
    return s.lower().strip()


def _select_best_release(
    releases: list[dict[str, Any]],
    local_album: str | None = None,
) -> dict[str, Any] | None:
    """Select the best release from a list of releases.

    Scoring criteria (in order of priority):
    1. Exact match on local album name (+100 points)
    2. Release type "Album" (+20), "EP" (+15), "Single" (+10), others (+0)
    3. Official status (+10 points)
    4. Has a release date (+5 points)
    5. Earlier release date (tiebreaker)

    This prevents soundtracks/compilations from being selected over
    the original album when a track appears on multiple releases.

    Args:
        releases: List of release dicts from MusicBrainz
        local_album: The album name from the user's local files (if available)

    Returns:
        Best matching release dict, or None if no releases
    """
    if not releases:
        return None

    if len(releases) == 1:
        return releases[0]

    local_album_normalized = _normalize_for_comparison(local_album)

    def score_release(release: dict[str, Any]) -> tuple[int, str]:
        """Score a release. Returns (score, date) for sorting."""
        score = 0
        release_title = release.get("title", "")

        # Priority 1: Exact match on local album name (+100)
        if local_album_normalized and _normalize_for_comparison(release_title) == local_album_normalized:
            score += 100

        # Priority 2: Release type preference
        # Release type is in release-group if present
        release_group = release.get("release-group", {})
        primary_type = release_group.get("primary-type", "").lower()
        secondary_types = [t.lower() for t in release_group.get("secondary-type-list", [])]

        # Penalize compilations, soundtracks, and other secondary types
        if "compilation" in secondary_types or "soundtrack" in secondary_types:
            score -= 30  # Strong penalty for compilations/soundtracks
        elif primary_type == "album":
            score += 20
        elif primary_type == "ep":
            score += 15
        elif primary_type == "single":
            score += 10

        # Priority 3: Official status (+10)
        status = release.get("status", "").lower()
        if status == "official":
            score += 10

        # Priority 4: Has a release date (+5)
        release_date = release.get("date", "")
        if release_date:
            score += 5

        # Use date as secondary sort key (earlier = better)
        # Pad with "9999" so missing dates sort last
        date_key = release_date if release_date else "9999"

        return (score, date_key)

    # Sort by score descending, then by date ascending
    scored_releases = [(release, score_release(release)) for release in releases]
    scored_releases.sort(key=lambda x: (-x[1][0], x[1][1]))

    best_release = scored_releases[0][0]
    best_score = scored_releases[0][1]

    # Log when we're making a non-trivial choice
    if len(releases) > 1:
        logger.debug(
            f"Selected release '{best_release.get('title')}' (score={best_score[0]}) "
            f"from {len(releases)} candidates"
            + (f" (local album: '{local_album}')" if local_album else "")
        )

    return best_release


def get_recording_by_id(
    recording_id: str,
    local_album: str | None = None,
) -> dict[str, Any] | None:
    """Get detailed recording info from MusicBrainz by recording ID.

    Args:
        recording_id: MusicBrainz recording UUID
        local_album: The album name from the user's local files (for better release selection)

    Returns:
        Dict with recording metadata or None on error
    """
    try:
        result = musicbrainzngs.get_recording_by_id(
            recording_id,
            includes=["artists", "releases", "tags", "ratings"],
        )

        recording = result.get("recording", {})
        if not recording:
            return None

        # Extract relevant data
        metadata: dict[str, Any] = {
            "musicbrainz_recording_id": recording.get("id"),
            "title": recording.get("title"),
            "length_ms": int(recording.get("length", 0)) if recording.get("length") else None,
        }

        # Extract artist info
        artists = recording.get("artist-credit", [])
        if artists:
            artist_names = []
            artist_ids = []
            for credit in artists:
                if isinstance(credit, dict) and "artist" in credit:
                    artist = credit["artist"]
                    artist_names.append(artist.get("name", ""))
                    artist_ids.append(artist.get("id", ""))
            metadata["artist"] = ", ".join(artist_names)
            metadata["musicbrainz_artist_ids"] = artist_ids

        # Select the best release (not just the first one)
        releases = recording.get("release-list", [])
        release = _select_best_release(releases, local_album)
        if release:
            metadata["album"] = release.get("title")
            metadata["musicbrainz_release_id"] = release.get("id")
            metadata["release_date"] = release.get("date")

            # Get release group info if available
            if "release-group" in release:
                rg = release["release-group"]
                metadata["musicbrainz_release_group_id"] = rg.get("id")

        # Extract tags (genres)
        tags = recording.get("tag-list", [])
        if tags:
            # Sort by count and get top tags
            sorted_tags = sorted(tags, key=lambda t: int(t.get("count", 0)), reverse=True)
            metadata["tags"] = [t.get("name") for t in sorted_tags[:5]]

        # Extract rating
        if "rating" in recording:
            rating = recording["rating"]
            metadata["rating"] = float(rating.get("value", 0))
            metadata["rating_count"] = int(rating.get("votes-count", 0))

        return metadata

    except musicbrainzngs.WebServiceError as e:
        logger.error(f"MusicBrainz API error for recording {recording_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error fetching recording {recording_id}: {e}")
        return None


def search_recording(
    title: str,
    artist: str | None = None,
    local_album: str | None = None,
) -> dict[str, Any] | None:
    """Search for a recording on MusicBrainz.

    Args:
        title: Track title
        artist: Artist name (optional but recommended)
        local_album: The album name from the user's local files (for better release selection)

    Returns:
        Best matching recording metadata or None
    """
    try:
        query = f'recording:"{title}"'
        if artist:
            query += f' AND artist:"{artist}"'

        result = musicbrainzngs.search_recordings(
            query=query,
            limit=5,
        )

        recordings = result.get("recording-list", [])
        if not recordings:
            return None

        # Get the first (best) match
        best_match = recordings[0]

        # Fetch full details using the recording ID
        return get_recording_by_id(best_match.get("id"), local_album=local_album)

    except musicbrainzngs.WebServiceError as e:
        logger.error(f"MusicBrainz search error for '{title}': {e}")
        return None
    except Exception as e:
        logger.error(f"Error searching for '{title}': {e}")
        return None


def get_artist_by_id(artist_id: str) -> dict[str, Any] | None:
    """Get artist info from MusicBrainz.

    Args:
        artist_id: MusicBrainz artist UUID

    Returns:
        Dict with artist metadata or None on error
    """
    try:
        result = musicbrainzngs.get_artist_by_id(
            artist_id,
            includes=["tags", "ratings", "url-rels"],
        )

        artist = result.get("artist", {})
        if not artist:
            return None

        metadata: dict[str, Any] = {
            "musicbrainz_artist_id": artist.get("id"),
            "name": artist.get("name"),
            "sort_name": artist.get("sort-name"),
            "type": artist.get("type"),
            "country": artist.get("country"),
            "disambiguation": artist.get("disambiguation"),
        }

        # Life span
        if "life-span" in artist:
            lifespan = artist["life-span"]
            metadata["begin_date"] = lifespan.get("begin")
            metadata["end_date"] = lifespan.get("end")
            metadata["ended"] = lifespan.get("ended", False)

        # Tags/genres
        tags = artist.get("tag-list", [])
        if tags:
            sorted_tags = sorted(tags, key=lambda t: int(t.get("count", 0)), reverse=True)
            metadata["tags"] = [t.get("name") for t in sorted_tags[:5]]

        # External URLs
        urls = []
        for rel in artist.get("url-relation-list", []):
            url_type = rel.get("type")
            url = rel.get("target")
            if url_type and url:
                urls.append({"type": url_type, "url": url})
        metadata["urls"] = urls

        return metadata

    except musicbrainzngs.WebServiceError as e:
        logger.error(f"MusicBrainz API error for artist {artist_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error fetching artist {artist_id}: {e}")
        return None


def get_release_by_id(release_id: str) -> dict[str, Any] | None:
    """Get release (album) info from MusicBrainz.

    Args:
        release_id: MusicBrainz release UUID

    Returns:
        Dict with release metadata or None on error
    """
    try:
        result = musicbrainzngs.get_release_by_id(
            release_id,
            includes=["artists", "labels", "recordings", "release-groups", "tags"],
        )

        release = result.get("release", {})
        if not release:
            return None

        metadata: dict[str, Any] = {
            "musicbrainz_release_id": release.get("id"),
            "title": release.get("title"),
            "date": release.get("date"),
            "country": release.get("country"),
            "status": release.get("status"),
            "barcode": release.get("barcode"),
        }

        # Artists
        artists = release.get("artist-credit", [])
        if artists:
            artist_names = []
            for credit in artists:
                if isinstance(credit, dict) and "artist" in credit:
                    artist_names.append(credit["artist"].get("name", ""))
            metadata["artist"] = ", ".join(artist_names)

        # Labels
        labels = release.get("label-info-list", [])
        if labels:
            label_info = labels[0]
            if "label" in label_info:
                metadata["label"] = label_info["label"].get("name")
            metadata["catalog_number"] = label_info.get("catalog-number")

        # Release group (for album type)
        rg = release.get("release-group", {})
        if rg:
            metadata["release_group_id"] = rg.get("id")
            metadata["release_type"] = rg.get("type")  # Album, Single, EP, etc.

        # Track count
        media = release.get("medium-list", [])
        if media:
            track_count = sum(int(m.get("track-count", 0)) for m in media)
            metadata["track_count"] = track_count

        return metadata

    except musicbrainzngs.WebServiceError as e:
        logger.error(f"MusicBrainz API error for release {release_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error fetching release {release_id}: {e}")
        return None


def enrich_track(
    title: str | None = None,
    artist: str | None = None,
    album: str | None = None,
    musicbrainz_recording_id: str | None = None,
) -> dict[str, Any] | None:
    """Enrich track metadata from MusicBrainz.

    Tries to use recording ID first, falls back to search.

    Args:
        title: Track title (for search fallback)
        artist: Artist name (for search fallback)
        album: Album name from local files (for better release selection)
        musicbrainz_recording_id: MusicBrainz recording ID (preferred)

    Returns:
        Enriched metadata dict or None
    """
    # Try by ID first (most reliable)
    if musicbrainz_recording_id:
        result = get_recording_by_id(musicbrainz_recording_id, local_album=album)
        if result:
            logger.info(f"Enriched via MusicBrainz ID: {result.get('title')} by {result.get('artist')}")
            return result

    # Fall back to search
    if title:
        result = search_recording(title, artist, local_album=album)
        if result:
            logger.info(f"Enriched via MusicBrainz search: {result.get('title')} by {result.get('artist')}")
            return result

    return None


def search_artist(name: str) -> dict[str, Any] | None:
    """Search for an artist on MusicBrainz.

    Args:
        name: Artist name to search

    Returns:
        Best matching artist info or None
    """
    try:
        result = musicbrainzngs.search_artists(artist=name, limit=5)
        artists = result.get("artist-list", [])
        if not artists:
            return None

        # Get the best match (highest score)
        best_match = artists[0]
        return {
            "musicbrainz_artist_id": best_match.get("id"),
            "name": best_match.get("name"),
            "sort_name": best_match.get("sort-name"),
            "type": best_match.get("type"),
            "country": best_match.get("country"),
            "score": int(best_match.get("ext:score", 0)),
        }

    except musicbrainzngs.WebServiceError as e:
        logger.error(f"MusicBrainz artist search error for '{name}': {e}")
        return None
    except Exception as e:
        logger.error(f"Error searching artist '{name}': {e}")
        return None


def get_artist_releases_recent(
    artist_id: str,
    days_back: int = 90,
    release_types: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Get recent releases by an artist from MusicBrainz.

    Args:
        artist_id: MusicBrainz artist UUID
        days_back: Number of days to look back
        release_types: Filter by types (Album, Single, EP, etc.)

    Returns:
        List of recent release dicts
    """
    from datetime import datetime, timedelta

    if release_types is None:
        release_types = ["Album", "Single", "EP"]

    cutoff_date = datetime.now() - timedelta(days=days_back)
    recent_releases = []

    try:
        # Browse release groups by artist
        offset = 0
        limit = 100

        while True:
            result = musicbrainzngs.browse_release_groups(
                artist=artist_id,
                release_type=release_types,
                limit=limit,
                offset=offset,
            )

            release_groups = result.get("release-group-list", [])
            if not release_groups:
                break

            for rg in release_groups:
                first_release = rg.get("first-release-date", "")
                if not first_release:
                    continue

                # Parse release date (can be YYYY, YYYY-MM, or YYYY-MM-DD)
                try:
                    if len(first_release) == 4:  # YYYY
                        release_date = datetime.strptime(first_release, "%Y")
                    elif len(first_release) == 7:  # YYYY-MM
                        release_date = datetime.strptime(first_release, "%Y-%m")
                    else:  # YYYY-MM-DD
                        release_date = datetime.strptime(first_release, "%Y-%m-%d")

                    if release_date >= cutoff_date:
                        recent_releases.append({
                            "musicbrainz_release_group_id": rg.get("id"),
                            "title": rg.get("title"),
                            "release_type": rg.get("type") or rg.get("primary-type"),
                            "release_date": first_release,
                            "release_date_parsed": release_date.isoformat(),
                        })
                except ValueError:
                    continue

            # Check if there are more pages
            total = result.get("release-group-count", 0)
            offset += limit
            if offset >= total:
                break

        return recent_releases

    except musicbrainzngs.WebServiceError as e:
        logger.error(f"MusicBrainz browse error for artist {artist_id}: {e}")
        return []
    except Exception as e:
        logger.error(f"Error getting releases for artist {artist_id}: {e}")
        return []
