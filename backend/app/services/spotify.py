"""Spotify integration service for OAuth and sync."""

import logging
import secrets
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import spotipy
from spotipy.oauth2 import SpotifyOAuth
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import (
    ExternalTrack,
    ExternalTrackSource,
    Playlist,
    PlaylistTrack,
    ProfileExternalFavorite,
    SpotifyFavorite,
    SpotifyProfile,
    Track,
)
from app.services.app_settings import get_app_settings_service
from app.services.spotify_compat import SpotifyRateLimitError
from app.utils.time import utcnow

logger = logging.getLogger(__name__)


class SpotifyService:
    """Handles Spotify OAuth and API interactions."""

    # OAuth scopes needed for sync
    SCOPES = [
        "user-library-read",       # Saved tracks
        "user-top-read",           # Top tracks/artists
        "user-read-recently-played",  # Recently played
        "playlist-read-private",   # User playlists
    ]

    def __init__(self) -> None:
        # Redirect to backend OAuth callback endpoint
        # Derived from FRONTEND_URL setting
        base_url = settings.frontend_url or "http://localhost:4400"
        self.redirect_uri = f"{base_url.rstrip('/')}/api/v1/spotify/callback"

    def _get_credentials(self) -> tuple[str | None, str | None]:
        """Get Spotify credentials with proper precedence."""
        settings_service = get_app_settings_service()
        client_id = settings_service.get_effective("spotify_client_id")
        client_secret = settings_service.get_effective("spotify_client_secret")
        return client_id, client_secret

    def is_configured(self) -> bool:
        """Check if Spotify credentials are configured."""
        client_id, client_secret = self._get_credentials()
        return bool(client_id and client_secret)

    def get_auth_url(self, profile_id: UUID) -> tuple[str, str]:
        """Generate OAuth authorization URL.

        Args:
            profile_id: Device profile ID to associate with Spotify connection

        Returns:
            Tuple of (auth_url, state_token)
        """
        client_id, client_secret = self._get_credentials()

        # Create state token that encodes profile_id
        state = f"{profile_id}:{secrets.token_urlsafe(16)}"

        oauth = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=self.redirect_uri,
            scope=" ".join(self.SCOPES),
            state=state,
        )

        auth_url = oauth.get_authorize_url()
        return auth_url, state

    async def handle_callback(
        self,
        db: AsyncSession,
        code: str,
        state: str,
    ) -> SpotifyProfile:
        """Handle OAuth callback and store tokens.

        Args:
            db: Database session
            code: Authorization code from Spotify
            state: State token to verify profile

        Returns:
            SpotifyProfile with tokens stored
        """
        # Extract profile_id from state
        try:
            profile_id_str, _ = state.split(":", 1)
            profile_id = UUID(profile_id_str)
        except (ValueError, AttributeError):
            raise ValueError("Invalid OAuth state")

        # Exchange code for tokens
        client_id, client_secret = self._get_credentials()
        oauth = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=self.redirect_uri,
            scope=" ".join(self.SCOPES),
        )

        token_info = oauth.get_access_token(code, as_dict=True)

        # Get Spotify user profile
        sp = spotipy.Spotify(auth=token_info["access_token"], requests_timeout=30)
        spotify_user = sp.current_user()

        # Calculate token expiry
        expires_at = utcnow() + timedelta(seconds=token_info.get("expires_in", 3600))

        # Upsert SpotifyProfile
        result = await db.execute(
            select(SpotifyProfile).where(SpotifyProfile.profile_id == profile_id)
        )
        spotify_profile = result.scalar_one_or_none()

        if spotify_profile:
            spotify_profile.spotify_user_id = spotify_user["id"]
            spotify_profile.access_token = token_info["access_token"]
            spotify_profile.refresh_token = token_info.get("refresh_token")
            spotify_profile.token_expires_at = expires_at
        else:
            spotify_profile = SpotifyProfile(
                profile_id=profile_id,
                spotify_user_id=spotify_user["id"],
                access_token=token_info["access_token"],
                refresh_token=token_info.get("refresh_token"),
                token_expires_at=expires_at,
                sync_mode="periodic",
            )
            db.add(spotify_profile)

        await db.commit()
        await db.refresh(spotify_profile)
        return spotify_profile

    async def get_client(self, db: AsyncSession, profile_id: UUID) -> spotipy.Spotify | None:
        """Get authenticated Spotify client for a device profile.

        Handles token refresh automatically.
        """
        result = await db.execute(
            select(SpotifyProfile).where(SpotifyProfile.profile_id == profile_id)
        )
        spotify_profile = result.scalar_one_or_none()

        if not spotify_profile or not spotify_profile.access_token:
            logger.warning(f"No SpotifyProfile found for profile {profile_id}")
            return None

        # Check if token needs refresh
        if spotify_profile.token_expires_at and spotify_profile.token_expires_at < utcnow():
            logger.info(f"Token expired for {profile_id}, refreshing...")
            if spotify_profile.refresh_token:
                try:
                    spotify_profile = await self._refresh_token(db, spotify_profile)
                    logger.info(f"Token refreshed successfully for {profile_id}")
                except Exception as e:
                    logger.error(f"Token refresh failed for {profile_id}: {e}")
                    return None
            else:
                logger.error(f"No refresh token available for {profile_id}")
                return None

        from app.services.spotify_compat import SpotifyCompat

        return SpotifyCompat(
            spotipy.Spotify(
                auth=spotify_profile.access_token,
                requests_timeout=30,
                retries=0,  # Don't let spotipy sleep on 429 — we handle rate limits ourselves
            ),
            token=spotify_profile.access_token,
        )

    async def _refresh_token(
        self,
        db: AsyncSession,
        spotify_profile: SpotifyProfile,
    ) -> SpotifyProfile:
        """Refresh expired access token."""
        client_id, client_secret = self._get_credentials()
        oauth = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=self.redirect_uri,
        )

        token_info = oauth.refresh_access_token(spotify_profile.refresh_token)

        spotify_profile.access_token = token_info["access_token"]
        if "refresh_token" in token_info:
            spotify_profile.refresh_token = token_info["refresh_token"]
        spotify_profile.token_expires_at = utcnow() + timedelta(
            seconds=token_info.get("expires_in", 3600)
        )

        await db.commit()
        await db.refresh(spotify_profile)
        return spotify_profile


class SpotifySyncService:
    """Syncs Spotify favorites and matches to local library."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.spotify_service = SpotifyService()

    async def sync_favorites(self, profile_id: UUID) -> dict[str, int]:
        """Sync profile's Spotify saved tracks to local database.

        Returns:
            Dict with sync statistics
        """
        logger.info(f"Starting Spotify sync for profile {profile_id}")
        client = await self.spotify_service.get_client(self.db, profile_id)
        if not client:
            logger.error(f"No Spotify client available for profile {profile_id}")
            raise ValueError("Spotify not connected")

        stats = {"fetched": 0, "new": 0, "matched": 0, "unmatched": 0}

        # Fetch saved tracks (paginated)
        offset = 0
        limit = 50

        while True:
            try:
                results = client.current_user_saved_tracks(limit=limit, offset=offset)
                logger.info(f"Spotify API returned {len(results.get('items', []))} items at offset {offset}")
            except Exception as e:
                logger.error(f"Spotify API error: {e}")
                raise ValueError(f"Spotify API error: {e}")

            tracks = results.get("items", [])

            if not tracks:
                break

            for item in tracks:
                spotify_track = item["track"]
                if not spotify_track:
                    continue

                stats["fetched"] += 1
                added_at = item.get("added_at")

                # Check if already synced
                existing = await self.db.execute(
                    select(SpotifyFavorite).where(
                        SpotifyFavorite.profile_id == profile_id,
                        SpotifyFavorite.spotify_track_id == spotify_track["id"],
                    )
                )
                favorite = existing.scalar_one_or_none()

                # Try to match to local library
                local_match = await self._match_to_local(spotify_track)

                if favorite:
                    # Update match if found
                    if local_match and not favorite.matched_track_id:
                        favorite.matched_track_id = local_match.id
                        stats["matched"] += 1
                        # Clean up external favorite if one was created for this track
                        await self._remove_external_favorite_for_spotify_id(
                            profile_id, favorite.spotify_track_id
                        )
                else:
                    # Create new favorite
                    favorite = SpotifyFavorite(
                        profile_id=profile_id,
                        spotify_track_id=spotify_track["id"],
                        matched_track_id=local_match.id if local_match else None,
                        track_data=self._extract_track_data(spotify_track),
                        added_at=datetime.fromisoformat(added_at.replace("Z", "+00:00")) if added_at else None,
                    )
                    self.db.add(favorite)
                    stats["new"] += 1

                    if local_match:
                        stats["matched"] += 1
                    else:
                        stats["unmatched"] += 1

            offset += limit

            # Safety limit
            if offset > 2000:
                break

        # Promote unmatched favorites to external favorites
        promoted = await self._promote_unmatched_to_external_favorites(profile_id)
        stats["external_favorites"] = promoted

        # Update last sync time
        profile_result = await self.db.execute(
            select(SpotifyProfile).where(SpotifyProfile.profile_id == profile_id)
        )
        spotify_profile = profile_result.scalar_one_or_none()
        if spotify_profile:
            spotify_profile.last_sync_at = utcnow()

        await self.db.commit()
        logger.info(f"Spotify sync completed for profile {profile_id}: {stats}")
        return stats

    async def sync_top_tracks(self, profile_id: UUID, time_range: str = "medium_term") -> dict[str, int]:
        """Sync profile's top tracks.

        Args:
            time_range: short_term (4 weeks), medium_term (6 months), long_term (years)
        """
        client = await self.spotify_service.get_client(self.db, profile_id)
        if not client:
            raise ValueError("Spotify not connected")

        stats = {"fetched": 0, "new": 0, "matched": 0}

        results = client.current_user_top_tracks(limit=50, time_range=time_range)

        for spotify_track in results.get("items", []):
            stats["fetched"] += 1

            # Check if already exists
            existing = await self.db.execute(
                select(SpotifyFavorite).where(
                    SpotifyFavorite.profile_id == profile_id,
                    SpotifyFavorite.spotify_track_id == spotify_track["id"],
                )
            )

            if existing.scalar_one_or_none():
                continue

            local_match = await self._match_to_local(spotify_track)

            favorite = SpotifyFavorite(
                profile_id=profile_id,
                spotify_track_id=spotify_track["id"],
                matched_track_id=local_match.id if local_match else None,
                track_data=self._extract_track_data(spotify_track),
            )
            self.db.add(favorite)
            stats["new"] += 1

            if local_match:
                stats["matched"] += 1

        await self.db.commit()
        return stats

    async def get_unmatched_favorites(self, profile_id: UUID, limit: int = 50) -> list[dict[str, Any]]:
        """Get Spotify favorites that don't have local matches."""
        result = await self.db.execute(
            select(SpotifyFavorite)
            .where(
                SpotifyFavorite.profile_id == profile_id,
                SpotifyFavorite.matched_track_id.is_(None),
            )
            .order_by(SpotifyFavorite.added_at.desc())
            .limit(limit)
        )
        favorites = result.scalars().all()

        return [
            {
                "spotify_id": f.spotify_track_id,
                "name": f.track_data.get("name"),
                "artist": f.track_data.get("artist"),
                "album": f.track_data.get("album"),
                "added_at": f.added_at.isoformat() if f.added_at else None,
            }
            for f in favorites
        ]

    async def get_sync_stats(self, profile_id: UUID) -> dict[str, Any]:
        """Get sync statistics for a profile."""
        # Total favorites
        total = await self.db.scalar(
            select(func.count(SpotifyFavorite.id)).where(
                SpotifyFavorite.profile_id == profile_id
            )
        ) or 0

        # Matched favorites
        matched = await self.db.scalar(
            select(func.count(SpotifyFavorite.id)).where(
                SpotifyFavorite.profile_id == profile_id,
                SpotifyFavorite.matched_track_id.isnot(None),
            )
        ) or 0

        # Get profile info
        profile_result = await self.db.execute(
            select(SpotifyProfile).where(SpotifyProfile.profile_id == profile_id)
        )
        spotify_profile = profile_result.scalar_one_or_none()

        return {
            "total_favorites": total,
            "matched": matched,
            "unmatched": total - matched,
            "match_rate": round(matched / total * 100, 1) if total > 0 else 0,
            "last_sync": spotify_profile.last_sync_at.isoformat() if spotify_profile and spotify_profile.last_sync_at else None,
            "spotify_user_id": spotify_profile.spotify_user_id if spotify_profile else None,
        }

    async def _promote_unmatched_to_external_favorites(
        self, profile_id: UUID
    ) -> int:
        """Promote unmatched SpotifyFavorites into ExternalTrack + ProfileExternalFavorite.

        Returns count of newly created external favorites.
        """
        result = await self.db.execute(
            select(SpotifyFavorite).where(
                SpotifyFavorite.profile_id == profile_id,
                SpotifyFavorite.matched_track_id.is_(None),
            )
        )
        unmatched = result.scalars().all()
        created = 0

        for fav in unmatched:
            spotify_id = fav.spotify_track_id
            track_data = fav.track_data or {}

            # Find or create ExternalTrack
            ext_result = await self.db.execute(
                select(ExternalTrack).where(ExternalTrack.spotify_id == spotify_id)
            )
            external_track = ext_result.scalar_one_or_none()

            if not external_track:
                external_track = ExternalTrack(
                    title=track_data.get("name") or "Unknown",
                    artist=track_data.get("artist") or "Unknown",
                    album=track_data.get("album") if isinstance(track_data.get("album"), str) else None,
                    duration_seconds=(track_data.get("duration_ms") or 0) / 1000.0,
                    spotify_id=spotify_id,
                    source=ExternalTrackSource.SPOTIFY_FAVORITE,
                    external_data={
                        "spotify_url": track_data.get("external_url"),
                        "album_id": track_data.get("album_id"),
                        "artist_id": track_data.get("artist_id"),
                    },
                )
                self.db.add(external_track)
                await self.db.flush()

            # Check if ProfileExternalFavorite already exists
            pef_result = await self.db.execute(
                select(ProfileExternalFavorite).where(
                    ProfileExternalFavorite.profile_id == profile_id,
                    ProfileExternalFavorite.external_track_id == external_track.id,
                )
            )
            if pef_result.scalar_one_or_none():
                continue

            pef = ProfileExternalFavorite(
                profile_id=profile_id,
                external_track_id=external_track.id,
                favorited_at=fav.added_at or utcnow(),
            )
            self.db.add(pef)
            created += 1

        logger.info(
            f"Promoted {created} unmatched Spotify favorites to external favorites "
            f"for profile {profile_id}"
        )
        return created

    async def _remove_external_favorite_for_spotify_id(
        self, profile_id: UUID, spotify_track_id: str
    ) -> None:
        """Remove external favorite when a Spotify track gets matched locally."""
        ext_result = await self.db.execute(
            select(ExternalTrack).where(ExternalTrack.spotify_id == spotify_track_id)
        )
        external_track = ext_result.scalar_one_or_none()
        if not external_track:
            return

        pef_result = await self.db.execute(
            select(ProfileExternalFavorite).where(
                ProfileExternalFavorite.profile_id == profile_id,
                ProfileExternalFavorite.external_track_id == external_track.id,
            )
        )
        pef = pef_result.scalar_one_or_none()
        if pef:
            await self.db.delete(pef)
            logger.debug(
                f"Removed external favorite for matched track {spotify_track_id} "
                f"(profile {profile_id})"
            )

    async def _match_to_local(self, spotify_track: dict[str, Any]) -> Track | None:
        """Try to match a Spotify track to local library.

        Matching priority:
        1. ISRC (International Standard Recording Code) - most reliable
        2. Exact artist + title match
        3. Contains match (substring)
        4. Fuzzy matching with rapidfuzz (threshold 85%)
        """
        from rapidfuzz import fuzz

        # Extract info from Spotify track
        isrc = spotify_track.get("external_ids", {}).get("isrc")
        track_name = spotify_track.get("name", "").lower().strip()
        artists = spotify_track.get("artists", [])
        artist_name = artists[0]["name"].lower().strip() if artists else ""

        # Normalize for matching - remove common variations
        def normalize(s: str) -> str:
            """Normalize string for matching."""
            import re
            # Remove featuring/feat variations
            s = re.sub(r'\s*[\(\[](feat\.?|ft\.?|featuring)[^\)\]]*[\)\]]', '', s, flags=re.IGNORECASE)
            # Remove remaster/remix annotations
            s = re.sub(r'\s*[\(\[][^\)\]]*(?:remaster|remix|version|edit)[^\)\]]*[\)\]]', '', s, flags=re.IGNORECASE)
            # Normalize apostrophes
            s = s.replace("'", "'").replace("'", "'").replace("`", "'")
            # Remove extra whitespace
            s = ' '.join(s.split())
            return s.strip()

        normalized_track_name = normalize(track_name)
        normalized_artist_name = normalize(artist_name)

        # 1. Try ISRC match
        if isrc:
            result = await self.db.execute(
                select(Track).where(Track.isrc == isrc)
            )
            match = result.scalar_one_or_none()
            if match:
                return match

        # 2. Try exact artist + title match
        if track_name and artist_name:
            result = await self.db.execute(
                select(Track).where(
                    func.lower(Track.title) == track_name,
                    func.lower(Track.artist) == artist_name,
                ).limit(1)
            )
            match = result.scalars().first()
            if match:
                return match

            # 3. Try partial match (title contains, artist contains)
            result = await self.db.execute(
                select(Track).where(
                    func.lower(Track.title).contains(track_name),
                    func.lower(Track.artist).contains(artist_name),
                ).limit(1)
            )
            match = result.scalars().first()
            if match:
                return match

        # 4. Fuzzy match with rapidfuzz
        if normalized_track_name and normalized_artist_name:
            # Get candidate tracks - limit to reasonable set for performance
            result = await self.db.execute(
                select(Track)
                .where(Track.title.isnot(None), Track.artist.isnot(None))
                .limit(5000)  # Safety limit
            )
            candidates = result.scalars().all()

            best_match: Track | None = None
            best_score: float = 0.0
            threshold = 85  # Minimum combined score to accept

            for track in candidates:
                if not track.title or not track.artist:
                    continue

                local_title = normalize(track.title.lower())
                local_artist = normalize(track.artist.lower())

                # Calculate fuzzy scores
                title_score = fuzz.ratio(normalized_track_name, local_title)
                artist_score = fuzz.ratio(normalized_artist_name, local_artist)

                # Combined score with weights (title matters more)
                combined = (title_score * 0.6) + (artist_score * 0.4)

                if combined >= threshold and combined > best_score:
                    best_score = combined
                    best_match = track

            if best_match:
                return best_match

        return None

    def _extract_track_data(self, spotify_track: dict[str, Any]) -> dict[str, Any]:
        """Extract relevant data from Spotify track object."""
        artists = spotify_track.get("artists", [])
        album = spotify_track.get("album", {})

        return {
            "name": spotify_track.get("name"),
            "artist": artists[0]["name"] if artists else None,
            "artist_id": artists[0]["id"] if artists else None,
            "album": album.get("name"),
            "album_id": album.get("id"),
            "duration_ms": spotify_track.get("duration_ms"),
            "external_url": spotify_track.get("external_urls", {}).get("spotify"),
        }


class SpotifyPlaylistService:
    """Service for importing and working with Spotify playlists."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.spotify_service = SpotifyService()
        self.sync_service = SpotifySyncService(db)

    async def list_playlists(
        self,
        profile_id: UUID,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List user's Spotify playlists.

        Args:
            profile_id: Profile with Spotify connection
            limit: Max playlists to return

        Returns:
            List of playlist metadata dicts
        """
        client = await self.spotify_service.get_client(self.db, profile_id)
        if not client:
            raise ValueError("Spotify not connected")

        results = client.current_user_playlists(limit=limit)
        playlists = []

        for playlist in results.get("items", []):
            images = playlist.get("images", [])
            playlists.append({
                "id": playlist.get("id"),
                "name": playlist.get("name"),
                "description": playlist.get("description"),
                "track_count": playlist.get("tracks", {}).get("total", 0),
                "image_url": images[0].get("url") if images else None,
                "external_url": playlist.get("external_urls", {}).get("spotify"),
                "owner": playlist.get("owner", {}).get("display_name"),
                "public": playlist.get("public"),
            })

        return playlists

    async def get_playlist_tracks(
        self,
        profile_id: UUID,
        spotify_playlist_id: str,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Get tracks from a Spotify playlist with local match info.

        Args:
            profile_id: Profile with Spotify connection
            spotify_playlist_id: Spotify playlist ID
            limit: Max tracks to return

        Returns:
            Dict with tracks list and match statistics
        """
        client = await self.spotify_service.get_client(self.db, profile_id)
        if not client:
            raise ValueError("Spotify not connected")

        # Get playlist details first
        playlist_info = client.playlist(spotify_playlist_id, fields="name,description")

        # Get tracks
        results = await client.playlist_items(spotify_playlist_id, limit=limit)
        tracks = []
        in_library = 0

        for item in results.get("items", []):
            track = item.get("track")
            if not track:
                continue

            # Check local match
            local_match = await self.sync_service._match_to_local(track)

            artists = track.get("artists", [])
            album = track.get("album", {})

            track_info = {
                "spotify_id": track.get("id"),
                "title": track.get("name"),
                "artist": artists[0]["name"] if artists else None,
                "album": album.get("name") if album else None,
                "duration_ms": track.get("duration_ms"),
                "in_library": local_match is not None,
                "local_track_id": str(local_match.id) if local_match else None,
            }
            tracks.append(track_info)

            if local_match:
                in_library += 1

        return {
            "playlist_name": playlist_info.get("name"),
            "playlist_description": playlist_info.get("description"),
            "tracks": tracks,
            "total": len(tracks),
            "in_library": in_library,
            "missing": len(tracks) - in_library,
            "match_rate": f"{(in_library / len(tracks) * 100):.0f}%" if tracks else "0%",
        }

    async def import_playlist(
        self,
        profile_id: UUID,
        spotify_playlist_id: str,
        name: str | None = None,
        description: str | None = None,
        include_missing: bool = True,
    ) -> Playlist:
        """Import a Spotify playlist to Familiar.

        Creates a local playlist with matched local tracks and optionally
        external track placeholders for missing tracks.

        Args:
            profile_id: Profile with Spotify connection
            spotify_playlist_id: Spotify playlist ID
            name: Override playlist name (uses Spotify name if not provided)
            description: Override description
            include_missing: Whether to include unmatched tracks as ExternalTrack entries

        Returns:
            The created Playlist with tracks
        """
        client = await self.spotify_service.get_client(self.db, profile_id)
        if not client:
            raise ValueError("Spotify not connected")

        # Get playlist details
        playlist_info = client.playlist(
            spotify_playlist_id,
            fields="name,description,images"
        )

        # Create local playlist
        playlist = Playlist(
            profile_id=profile_id,
            name=name or playlist_info.get("name") or "Imported Playlist",
            description=description or playlist_info.get("description"),
            is_auto_generated=False,
        )
        self.db.add(playlist)
        await self.db.flush()

        # Fetch all tracks (paginated)
        offset = 0
        limit = 100
        position = 0

        while True:
            results = await client.playlist_items(
                spotify_playlist_id,
                limit=limit,
                offset=offset
            )
            items = results.get("items", [])

            if not items:
                break

            for item in items:
                track = item.get("track")
                if not track:
                    continue

                # Try to match to local library
                local_match = await self.sync_service._match_to_local(track)

                if local_match:
                    # Add local track to playlist
                    playlist_track = PlaylistTrack(
                        playlist_id=playlist.id,
                        track_id=local_match.id,
                        position=position,
                    )
                    self.db.add(playlist_track)
                elif include_missing:
                    # Create external track and add to playlist
                    external_track = await self._create_external_track_from_spotify(
                        track,
                        playlist.id,
                        spotify_playlist_id,
                    )

                    playlist_track = PlaylistTrack(
                        playlist_id=playlist.id,
                        external_track_id=external_track.id,
                        position=position,
                    )
                    self.db.add(playlist_track)

                position += 1

            offset += limit

            # Safety limit
            if offset > 500:
                break

        await self.db.commit()
        await self.db.refresh(playlist)

        logger.info(
            f"Imported Spotify playlist '{playlist.name}' with {position} tracks "
            f"for profile {profile_id}"
        )

        return playlist

    async def _create_external_track_from_spotify(
        self,
        spotify_track: dict[str, Any],
        source_playlist_id: UUID,
        source_spotify_playlist_id: str,
    ) -> ExternalTrack:
        """Create an ExternalTrack from Spotify track data.

        If the track already exists (by spotify_id), returns existing.
        """
        spotify_id = spotify_track.get("id")

        # Check if already exists
        if spotify_id:
            result = await self.db.execute(
                select(ExternalTrack).where(ExternalTrack.spotify_id == spotify_id)
            )
            existing = result.scalar_one_or_none()
            if existing:
                return existing

        artists = spotify_track.get("artists", [])
        album = spotify_track.get("album", {})
        images = album.get("images", []) if album else []

        external_track = ExternalTrack(
            title=spotify_track.get("name") or "Unknown",
            artist=artists[0]["name"] if artists else "Unknown",
            album=album.get("name") if album else None,
            duration_seconds=(spotify_track.get("duration_ms") or 0) / 1000.0,
            year=self._parse_year(album.get("release_date")) if album else None,
            isrc=spotify_track.get("external_ids", {}).get("isrc"),
            spotify_id=spotify_id,
            source=ExternalTrackSource.SPOTIFY_PLAYLIST,
            source_playlist_id=source_playlist_id,
            source_spotify_playlist_id=source_spotify_playlist_id,
            external_data={
                "spotify_url": spotify_track.get("external_urls", {}).get("spotify"),
                "album_art": images[0].get("url") if images else None,
                "artist_id": artists[0]["id"] if artists else None,
                "album_id": album.get("id") if album else None,
            },
        )
        self.db.add(external_track)
        await self.db.flush()

        return external_track

    def _parse_year(self, date_str: str | None) -> int | None:
        """Parse year from Spotify date string (YYYY or YYYY-MM-DD)."""
        if not date_str:
            return None
        try:
            return int(date_str[:4])
        except (ValueError, TypeError):
            return None


class SpotifyArtistService:
    """Service for Spotify artist-related operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.spotify_service = SpotifyService()

    async def search_artist(
        self, profile_id: UUID, artist_name: str
    ) -> dict[str, Any] | None:
        """Search for an artist on Spotify.

        Args:
            profile_id: Profile with Spotify connection
            artist_name: Name to search for

        Returns:
            Artist info dict or None
        """
        client = await self.spotify_service.get_client(self.db, profile_id)
        if not client:
            return None

        try:
            results = client.search(q=artist_name, type="artist", limit=1)
            artists = results.get("artists", {}).get("items", [])
            if not artists:
                return None

            artist = artists[0]
            return {
                "id": artist.get("id"),
                "name": artist.get("name"),
                "genres": artist.get("genres", []),
                "images": artist.get("images", []),
                "external_url": artist.get("external_urls", {}).get("spotify"),
            }
        except SpotifyRateLimitError:
            raise
        except spotipy.SpotifyException as e:
            if e.http_status == 429:
                retry_after = int(e.headers.get("Retry-After", "60")) if e.headers else 60
                raise SpotifyRateLimitError(retry_after=retry_after) from e
            logger.error(f"Spotify artist search error: {e}")
            return None
        except Exception as e:
            logger.error(f"Spotify artist search error: {e}")
            return None

    async def get_artist_albums(
        self,
        profile_id: UUID,
        artist_id: str,
        album_type: str = "album,single",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get albums by artist from Spotify.

        Args:
            profile_id: Profile with Spotify connection
            artist_id: Spotify artist ID
            album_type: Comma-separated types (album, single, compilation)
            limit: Max albums to return

        Returns:
            List of album dicts
        """
        client = await self.spotify_service.get_client(self.db, profile_id)
        if not client:
            return []

        try:
            results = client.artist_albums(
                artist_id,
                album_type=album_type,
                limit=limit,
                country="US",  # Get US releases
            )
            albums = results.get("items", [])

            return [
                {
                    "id": album.get("id"),
                    "name": album.get("name"),
                    "release_date": album.get("release_date"),
                    "release_date_precision": album.get("release_date_precision"),
                    "album_type": album.get("album_type"),
                    "total_tracks": album.get("total_tracks"),
                    "images": album.get("images", []),
                    "external_url": album.get("external_urls", {}).get("spotify"),
                    "artists": [
                        {"id": a.get("id"), "name": a.get("name")}
                        for a in album.get("artists", [])
                    ],
                }
                for album in albums
            ]
        except SpotifyRateLimitError:
            raise
        except spotipy.SpotifyException as e:
            if e.http_status == 429:
                retry_after = int(e.headers.get("Retry-After", "60")) if e.headers else 60
                raise SpotifyRateLimitError(retry_after=retry_after) from e
            logger.error(f"Spotify get artist albums error: {e}")
            return []
        except Exception as e:
            logger.error(f"Spotify get artist albums error: {e}")
            return []

    async def get_artist_albums_recent(
        self,
        profile_id: UUID,
        artist_id: str,
        days_back: int = 90,
    ) -> list[dict[str, Any]]:
        """Get recent albums (released in the last N days) by artist.

        Args:
            profile_id: Profile with Spotify connection
            artist_id: Spotify artist ID
            days_back: Number of days to look back

        Returns:
            List of recent album dicts
        """
        from datetime import datetime, timedelta

        albums = await self.get_artist_albums(profile_id, artist_id)
        if not albums:
            return []

        cutoff_date = datetime.now() - timedelta(days=days_back)
        recent_albums = []

        for album in albums:
            release_date_str = album.get("release_date")
            if not release_date_str:
                continue

            # Parse release date (can be YYYY, YYYY-MM, or YYYY-MM-DD)
            try:
                precision = album.get("release_date_precision", "day")
                if precision == "year":
                    release_date = datetime.strptime(release_date_str, "%Y")
                elif precision == "month":
                    release_date = datetime.strptime(release_date_str, "%Y-%m")
                else:
                    release_date = datetime.strptime(release_date_str, "%Y-%m-%d")

                if release_date >= cutoff_date:
                    album["release_date_parsed"] = release_date.isoformat()
                    recent_albums.append(album)
            except ValueError:
                # Skip albums with unparseable dates
                continue

        return recent_albums
