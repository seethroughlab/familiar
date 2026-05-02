import { favoritesApi, getApiOrigin, libraryApi, playlistsApi, playTrackingApi, tracksApi, type FavoriteTrack, type PlaylistTrack } from '@familiar/frontend/src/api';
import { getSelectedProfileId } from '@familiar/frontend/src/services/profileSelection';
import { getCachedFavorites, resolveTrackIds } from '@familiar/frontend/src/services/playlistCache';
import { usePlayerStore } from '@familiar/frontend/src/player/playerStore';
import type { QueueSource } from '@familiar/frontend/src/player/playerStore.types';
import type { Track } from '@familiar/frontend/src/types';
import { createLogger } from '@familiar/frontend/src/utils/logger';
import { FamiliarAudio } from './plugins/familiarAudio';
import type {
  CarPlayFavoriteTrackSelectionEvent,
  CarPlayCollectionSnapshot,
  CarPlayLibraryBucketSnapshot,
  CarPlayLibrarySelectionEvent,
  CarPlayNowPlayingSnapshot,
  CarPlayPlaylistSelectionEvent,
  CarPlayPlaylistSnapshot,
  CarPlayPlaylistTrackSelectionEvent,
  CarPlayTrackSnapshot,
} from './carplayTypes';

const log = createLogger('CarPlayCoordinator');

const MAX_RECENT_TRACKS = 20;
const MAX_FAVORITES = 100;
const MAX_ARTISTS = 20;
const MAX_ARTIST_TRACKS = 40;
const MAX_ALBUMS = 20;
const MAX_ALBUM_TRACKS = 40;
const MAX_PLAYLISTS = 20;
const MAX_PLAYLIST_TRACKS = 50;
const RECENT_ARTIST_TRACK_SAMPLE_SIZE = 100;
const MAX_RECENT_ARTIST_TRACK_PAGES = 4;

function toTrackSnapshot(track: Track): CarPlayTrackSnapshot {
  const title = track.title || 'Unknown Track';
  const artist = track.artist || 'Unknown Artist';
  const album = track.album || null;

  return {
    id: track.id,
    title,
    subtitle: album ? `${artist} • ${album}` : artist,
    artist: track.artist,
    album: track.album,
    artworkUrl: track.id ? tracksApi.getArtworkUrl(track.id, 'thumb') : null,
  };
}

function toPlaylistQueueTrack(track: PlaylistTrack): Track {
  return {
    id: track.id,
    file_path: '',
    title: track.title || 'Unknown Track',
    artist: track.artist || 'Unknown Artist',
    album: track.album || null,
    album_artist: track.album_artist ?? null,
    album_type: (track.album_type as Track['album_type']) ?? 'album',
    track_number: track.track_number ?? null,
    disc_number: track.disc_number ?? null,
    year: track.year ?? null,
    genre: track.genre ?? null,
    duration_seconds: track.duration_seconds ?? null,
    format: track.format ?? null,
    analysis_version: track.analysis_version ?? 0,
    last_played_at: track.last_played_at ?? null,
    play_count: track.play_count ?? null,
  };
}

function toFavoriteQueueTrack(track: FavoriteTrack): Track {
  return {
    id: track.id,
    file_path: track.file_path || '',
    title: track.title || 'Unknown Track',
    artist: track.artist || 'Unknown Artist',
    album: track.album || null,
    album_artist: track.album_artist ?? null,
    album_type: (track.album_type as Track['album_type']) ?? 'album',
    track_number: track.track_number ?? null,
    disc_number: track.disc_number ?? null,
    year: track.year ?? null,
    genre: track.genre ?? null,
    duration_seconds: track.duration_seconds ?? null,
    format: track.format ?? null,
    analysis_version: track.analysis_version ?? 0,
    last_played_at: track.last_played_at ?? null,
    play_count: track.play_count ?? null,
  };
}

function toArtistQueueTrack(artistName: string, track: {
  id: string;
  title: string | null;
  album: string | null;
  track_number: number | null;
  duration_seconds: number | null;
  year: number | null;
}): Track {
  return {
    id: track.id,
    file_path: '',
    title: track.title || 'Unknown Track',
    artist: artistName,
    album: track.album || null,
    album_artist: null,
    album_type: 'album',
    track_number: track.track_number ?? null,
    disc_number: null,
    year: track.year ?? null,
    genre: null,
    duration_seconds: track.duration_seconds ?? null,
    format: null,
    analysis_version: 0,
  };
}

function toAlbumQueueTrack(
  albumArtist: string,
  albumName: string,
  albumArtistName: string | null,
  albumYear: number | null,
  albumGenre: string | null,
  track: {
    id: string;
    title: string | null;
    track_number: number | null;
    disc_number: number | null;
    duration_seconds: number | null;
  },
): Track {
  return {
    id: track.id,
    file_path: '',
    title: track.title || 'Unknown Track',
    artist: albumArtist,
    album: albumName,
    album_artist: albumArtistName,
    album_type: 'album',
    track_number: track.track_number ?? null,
    disc_number: track.disc_number ?? null,
    year: albumYear,
    genre: albumGenre,
    duration_seconds: track.duration_seconds ?? null,
    format: null,
    analysis_version: 0,
  };
}

function makeAlbumCollectionId(artist: string, album: string): string {
  return `${artist}::${album}`;
}

type BrowseQueueCache = {
  favoriteTracks: Track[];
  favoriteTrackIds: Set<string>;
  recentTracks: Track[];
  artistTracks: Map<string, Track[]>;
  albumTracks: Map<string, Track[]>;
  playlistTracks: Map<string, Track[]>;
};

class CarPlayCoordinator {
  private started = false;
  private cleanups: Array<() => void> = [];
  private browseRefreshPromise: Promise<void> | null = null;
  private browseRefreshQueued = false;
  private lastTrackId: string | null = null;
  private lastIsPlaying = false;
  private browseCache: BrowseQueueCache = {
    favoriteTracks: [],
    favoriteTrackIds: new Set(),
    recentTracks: [],
    artistTracks: new Map(),
    albumTracks: new Map(),
    playlistTracks: new Map(),
  };

  start(): void {
    if (this.started) return;
    this.started = true;
    log.info('start: registering listeners');

    this.registerPluginListeners();

    let lastSnapshot = this.getPlayerSnapshot();
    this.lastTrackId = lastSnapshot.currentTrack?.id ?? null;
    this.lastIsPlaying = lastSnapshot.isPlaying;

    const unsubscribe = usePlayerStore.subscribe(() => {
      const nextSnapshot = this.getPlayerSnapshot();
      const trackId = nextSnapshot.currentTrack?.id ?? null;
      const isPlaying = nextSnapshot.isPlaying;

      if (trackId !== this.lastTrackId || isPlaying !== this.lastIsPlaying) {
        this.lastTrackId = trackId;
        this.lastIsPlaying = isPlaying;
        void this.syncNowPlaying(nextSnapshot.currentTrack, isPlaying);
        if (trackId) {
          this.queueBrowseRefresh('player-state');
        }
      }

      lastSnapshot = nextSnapshot;
    });

    this.cleanups.push(unsubscribe);

    const onProfileInvalidated = () => {
      this.resetBrowseCache();
      void FamiliarAudio.clearCarPlayState().catch((error) => {
        log.warn('Failed to clear CarPlay state after profile invalidation', error);
      });
    };
    window.addEventListener('profile-invalidated', onProfileInvalidated);
    this.cleanups.push(() => window.removeEventListener('profile-invalidated', onProfileInvalidated));

    const onProfileSelected = () => {
      this.queueBrowseRefresh('profile-selected');
    };
    window.addEventListener('profile-selected', onProfileSelected);
    this.cleanups.push(() => window.removeEventListener('profile-selected', onProfileSelected));

    const onProfileCleared = () => {
      this.resetBrowseCache();
      void FamiliarAudio.clearCarPlayState().catch((error) => {
        log.warn('Failed to clear CarPlay state after profile clear', error);
      });
    };
    window.addEventListener('profile-cleared', onProfileCleared);
    this.cleanups.push(() => window.removeEventListener('profile-cleared', onProfileCleared));

    void this.syncNowPlaying(lastSnapshot.currentTrack, lastSnapshot.isPlaying);
    this.queueBrowseRefresh('startup');
    log.info('start: completed sync init');
  }

  private getPlayerSnapshot(): { currentTrack: Track | null; isPlaying: boolean } {
    const state = usePlayerStore.getState();
    return {
      currentTrack: state.currentTrack,
      isPlaying: state.isPlaying,
    };
  }

  private registerPluginListeners(): void {
    FamiliarAudio.addListener('carPlayConnected', () => {
      log.info('event: carPlayConnected received from native');
      this.queueBrowseRefresh('carplay-connected');
      const snapshot = this.getPlayerSnapshot();
      void this.syncNowPlaying(snapshot.currentTrack, snapshot.isPlaying);
    }).then((handle) => {
      this.cleanups.push(() => {
        void handle.remove();
      });
    }).catch((error) => {
      log.warn('Failed to register CarPlay connection listener', error);
    });

    FamiliarAudio.addListener('carPlaySelectFavoriteTrack', (event) => {
      this.handleFavoriteTrackSelection(event);
    }).then((handle) => {
      this.cleanups.push(() => {
        void handle.remove();
      });
    }).catch((error) => {
      log.warn('Failed to register CarPlay favorites listener', error);
    });

    FamiliarAudio.addListener('carPlaySelectLibraryItem', (event) => {
      this.handleLibrarySelection(event);
    }).then((handle) => {
      this.cleanups.push(() => {
        void handle.remove();
      });
    }).catch((error) => {
      log.warn('Failed to register CarPlay library listener', error);
    });

    FamiliarAudio.addListener('carPlaySelectPlaylist', (event) => {
      this.handlePlaylistSelection(event);
    }).then((handle) => {
      this.cleanups.push(() => {
        void handle.remove();
      });
    }).catch((error) => {
      log.warn('Failed to register CarPlay playlist listener', error);
    });

    FamiliarAudio.addListener('carPlaySelectPlaylistTrack', (event) => {
      this.handlePlaylistTrackSelection(event);
    }).then((handle) => {
      this.cleanups.push(() => {
        void handle.remove();
      });
    }).catch((error) => {
      log.warn('Failed to register CarPlay playlist track listener', error);
    });

    FamiliarAudio.addListener('favoriteToggled', ({ trackId }) => {
      if (this.browseCache.favoriteTrackIds.has(trackId)) {
        this.browseCache.favoriteTrackIds.delete(trackId);
      } else {
        this.browseCache.favoriteTrackIds.add(trackId);
      }

      const snapshot = this.getPlayerSnapshot();
      if (snapshot.currentTrack?.id === trackId) {
        void this.syncNowPlaying(snapshot.currentTrack, snapshot.isPlaying);
      }

      this.queueBrowseRefresh('favorite-toggled');
    }).then((handle) => {
      this.cleanups.push(() => {
        void handle.remove();
      });
    }).catch((error) => {
      log.warn('Failed to register favorite toggle listener', error);
    });
  }

  private queueBrowseRefresh(reason: string): void {
    log.info('queueBrowseRefresh', { reason, alreadyRunning: !!this.browseRefreshPromise });
    if (this.browseRefreshPromise) {
      this.browseRefreshQueued = true;
      return;
    }

    this.browseRefreshPromise = this.refreshBrowseState(reason)
      .catch((error: unknown) => {
        const status = (error as { response?: { status?: number } })?.response?.status;
        const message = (error as { message?: string })?.message;
        const stack = (error as { stack?: string })?.stack;
        log.error('Failed to refresh CarPlay browse state', { reason, status, message, stack });
      })
      .finally(() => {
        this.browseRefreshPromise = null;
        if (this.browseRefreshQueued) {
          this.browseRefreshQueued = false;
          this.queueBrowseRefresh('queued-refresh');
        }
      });
  }

  private async refreshBrowseState(reason: string): Promise<void> {
    const profileId = await getSelectedProfileId();
    log.info('refreshBrowseState profileId', { reason, profileId });
    if (!profileId) {
      this.resetBrowseCache();
      await FamiliarAudio.clearCarPlayState();
      return;
    }

    if (!getApiOrigin()) {
      log.warn('refreshBrowseState: no API origin set; skipping');
      await FamiliarAudio.clearCarPlayState();
      return;
    }

    log.info('builders starting');

    const errMessage = (error: unknown): string | undefined => (error as { message?: string })?.message;

    const [favorites, recentlyPlayed, artistBucket, albumBucket, playlists] = await Promise.all([
      this.buildFavorites().catch((error: unknown) => {
        log.warn('buildFavorites failed', { error: errMessage(error) });
        return { snapshot: [] as CarPlayTrackSnapshot[], tracks: [] as Track[] };
      }),
      this.buildRecentlyPlayedBucket().catch((error: unknown) => {
        log.warn('buildRecentlyPlayedBucket failed', { error: errMessage(error) });
        const snapshot: CarPlayLibraryBucketSnapshot = { id: 'recently-played', title: 'Recently Played', tracks: [] };
        return { snapshot, tracks: [] as Track[] };
      }),
      this.buildArtistsBucket().catch((error: unknown) => {
        log.warn('buildArtistsBucket failed', { error: errMessage(error) });
        const snapshot: CarPlayLibraryBucketSnapshot = { id: 'artists', title: 'Artists', collections: [] };
        return { snapshot, queueMap: new Map<string, Track[]>() };
      }),
      this.buildAlbumsBucket().catch((error: unknown) => {
        log.warn('buildAlbumsBucket failed', { error: errMessage(error) });
        const snapshot: CarPlayLibraryBucketSnapshot = { id: 'albums', title: 'Albums', collections: [] };
        return { snapshot, queueMap: new Map<string, Track[]>() };
      }),
      this.buildPlaylists().catch((error: unknown) => {
        log.warn('buildPlaylists failed', { error: errMessage(error) });
        return { snapshot: [] as CarPlayPlaylistSnapshot[], queueMap: new Map<string, Track[]>() };
      }),
    ]);

    log.info('builders done', {
      favs: favorites.tracks.length,
      recent: recentlyPlayed.tracks.length,
      artists: artistBucket.queueMap.size,
      albums: albumBucket.queueMap.size,
      playlists: playlists.queueMap.size,
    });

    const librarySnapshots: CarPlayLibraryBucketSnapshot[] = [
      recentlyPlayed.snapshot,
      artistBucket.snapshot,
      albumBucket.snapshot,
    ];

    this.browseCache = {
      favoriteTracks: favorites.tracks,
      favoriteTrackIds: new Set(favorites.tracks.map((track) => track.id)),
      recentTracks: recentlyPlayed.tracks,
      artistTracks: artistBucket.queueMap,
      albumTracks: albumBucket.queueMap,
      playlistTracks: playlists.queueMap,
    };

    log.info('syncing snapshots', {
      favs: favorites.snapshot.length,
      buckets: librarySnapshots.length,
      playlists: playlists.snapshot.length,
    });

    const results = await Promise.allSettled([
      FamiliarAudio.syncCarPlayFavorites({
        snapshot: JSON.stringify(favorites.snapshot),
      }),
      FamiliarAudio.syncCarPlayLibrary({
        snapshot: JSON.stringify(librarySnapshots),
      }),
      FamiliarAudio.syncCarPlayPlaylists({
        snapshot: JSON.stringify(playlists.snapshot),
      }),
    ]);

    for (const [index, result] of results.entries()) {
      if (result.status === 'rejected') {
        const channel = ['favorites', 'library', 'playlists'][index];
        log.warn(`syncCarPlay${channel} rejected`, { error: result.reason });
      }
    }

    log.info('snapshots synced');
  }

  private async syncNowPlaying(currentTrack: Track | null, isPlaying: boolean): Promise<void> {
    if (!currentTrack) {
      await FamiliarAudio.syncCarPlayNowPlaying({ snapshot: null });
      return;
    }

    const snapshot: CarPlayNowPlayingSnapshot = {
      trackId: currentTrack.id,
      title: currentTrack.title || 'Unknown Track',
      artist: currentTrack.artist || 'Unknown Artist',
      album: currentTrack.album || 'Unknown Album',
      artworkUrl: currentTrack.id ? tracksApi.getArtworkUrl(currentTrack.id, 'thumb') : null,
      isPlaying,
      isFavorite: this.browseCache.favoriteTrackIds.has(currentTrack.id),
    };

    await FamiliarAudio.syncCarPlayNowPlaying({
      snapshot: JSON.stringify(snapshot),
    });
  }

  private async buildFavorites(): Promise<{
    snapshot: CarPlayTrackSnapshot[];
    tracks: Track[];
  }> {
    const profileId = await getSelectedProfileId();

    try {
      const response = await favoritesApi.list(MAX_FAVORITES, 0);
      const tracks = response.favorites
        .slice(0, MAX_FAVORITES)
        .map(toFavoriteQueueTrack);

      if (tracks.length > 0 || response.total === 0 || !profileId) {
        return {
          snapshot: tracks.map(toTrackSnapshot),
          tracks,
        };
      }
    } catch (error) {
      log.warn('Falling back to cached favorites for CarPlay', { error });
    }

    const cached = profileId ? await getCachedFavorites(profileId) : undefined;
    const cachedTracks = cached
      ? await resolveTrackIds(cached.trackIds.slice(0, MAX_FAVORITES))
      : [];
    const tracks = cachedTracks.map((track) => ({
      id: track.id,
      file_path: '',
      title: track.title || 'Unknown Track',
      artist: track.artist || 'Unknown Artist',
      album: track.album || null,
      album_artist: track.albumArtist ?? null,
      album_type: 'album' as const,
      track_number: track.trackNumber ?? null,
      disc_number: track.discNumber ?? null,
      year: track.year ?? null,
      genre: track.genre ?? null,
      duration_seconds: track.durationSeconds ?? null,
      format: null,
      analysis_version: 0,
    }));

    return {
      snapshot: tracks.map(toTrackSnapshot),
      tracks,
    };
  }

  private async buildRecentlyPlayedBucket(): Promise<{
    snapshot: CarPlayLibraryBucketSnapshot;
    tracks: Track[];
  }> {
    const stats = await playTrackingApi.getStats(MAX_RECENT_TRACKS);
    const orderedIds = stats.top_tracks.map((track) => track.id);

    if (orderedIds.length === 0) {
      return {
        snapshot: {
          id: 'recently-played',
          title: 'Recently Played',
          tracks: [],
        },
        tracks: [],
      };
    }

    const fetchedTracks = await tracksApi.getBatch(orderedIds);
    const byId = new Map(fetchedTracks.map((track) => [track.id, track] as const));
    const orderedTracks = orderedIds
      .map((trackId) => byId.get(trackId))
      .filter((track): track is Track => Boolean(track))
      .slice(0, MAX_RECENT_TRACKS);

    return {
      snapshot: {
        id: 'recently-played',
        title: 'Recently Played',
        tracks: orderedTracks.map(toTrackSnapshot),
      },
      tracks: orderedTracks,
    };
  }

  private async buildArtistsBucket(): Promise<{
    snapshot: CarPlayLibraryBucketSnapshot;
    queueMap: Map<string, Track[]>;
  }> {
    let artistNames = await this.getRecentlyPlayedArtistNames();

    if (artistNames.length === 0) {
      const response = await libraryApi.listArtists({
        sort_by: 'track_count',
        page_size: MAX_ARTISTS,
      });
      artistNames = response.items
        .slice(0, MAX_ARTISTS)
        .map((artist) => artist.name);
    }

    const collections = await Promise.all(artistNames.map(async (artistName) => {
      const artist = await libraryApi.getArtist(artistName);
      const queueTracks = artist.tracks
        .slice(0, MAX_ARTIST_TRACKS)
        .map((track) => toArtistQueueTrack(artist.name, track));

      const snapshot: CarPlayCollectionSnapshot = {
        id: artist.name,
        title: artist.name,
        subtitle: `${artist.track_count} tracks`,
        tracks: queueTracks.map(toTrackSnapshot),
      };

      return {
        id: artist.name,
        queueTracks,
        snapshot,
      };
    }));

    const queueMap = new Map<string, Track[]>();
    for (const collection of collections) {
      queueMap.set(collection.id, collection.queueTracks);
    }

    return {
      snapshot: {
        id: 'artists',
        title: 'Artists',
        collections: collections.map((collection) => collection.snapshot),
      },
      queueMap,
    };
  }

  private async getRecentlyPlayedArtistNames(): Promise<string[]> {
    const seen = new Set<string>();
    const recentArtistNames: string[] = [];

    for (let page = 1; page <= MAX_RECENT_ARTIST_TRACK_PAGES; page += 1) {
      const response = await tracksApi.list({
        page,
        page_size: RECENT_ARTIST_TRACK_SAMPLE_SIZE,
        sort_by: 'lastPlayed',
        sort_order: 'desc',
      });

      for (const track of response.items) {
        const artistName = track.artist || track.album_artist || null;
        if (!artistName) continue;
        if (seen.has(artistName)) continue;

        seen.add(artistName);
        recentArtistNames.push(artistName);

        if (recentArtistNames.length >= MAX_ARTISTS) {
          return recentArtistNames;
        }
      }

      if (response.items.length < RECENT_ARTIST_TRACK_SAMPLE_SIZE) {
        break;
      }
    }

    return recentArtistNames;
  }

  private async buildAlbumsBucket(): Promise<{
    snapshot: CarPlayLibraryBucketSnapshot;
    queueMap: Map<string, Track[]>;
  }> {
    const response = await libraryApi.listAlbums({
      page_size: MAX_ALBUMS * 2,
    });

    const sortedAlbums = [...response.items]
      .sort((a, b) => {
        const yearDelta = (b.year ?? 0) - (a.year ?? 0);
        if (yearDelta !== 0) return yearDelta;
        const artistCompare = a.artist.localeCompare(b.artist);
        if (artistCompare !== 0) return artistCompare;
        return a.name.localeCompare(b.name);
      })
      .slice(0, MAX_ALBUMS);

    const collections = await Promise.all(sortedAlbums.map(async (albumSummary) => {
      const album = await libraryApi.getAlbum(albumSummary.artist, albumSummary.name);
      const queueTracks = album.tracks
        .slice(0, MAX_ALBUM_TRACKS)
        .map((track) => toAlbumQueueTrack(
          album.artist,
          album.name,
          album.album_artist,
          album.year,
          album.genre,
          track,
        ));
      const collectionId = makeAlbumCollectionId(album.artist, album.name);
      const snapshot: CarPlayCollectionSnapshot = {
        id: collectionId,
        title: album.name,
        subtitle: album.artist,
        tracks: queueTracks.map(toTrackSnapshot),
      };

      return {
        id: collectionId,
        queueTracks,
        snapshot,
      };
    }));

    const queueMap = new Map<string, Track[]>();
    for (const collection of collections) {
      queueMap.set(collection.id, collection.queueTracks);
    }

    return {
      snapshot: {
        id: 'albums',
        title: 'Albums',
        collections: collections.map((collection) => collection.snapshot),
      },
      queueMap,
    };
  }

  private async buildPlaylists(): Promise<{
    snapshot: CarPlayPlaylistSnapshot[];
    queueMap: Map<string, Track[]>;
  }> {
    const playlistSummaries = await playlistsApi.list(true);
    const selectedPlaylists = playlistSummaries.slice(0, MAX_PLAYLISTS);

    const playlists = await Promise.all(selectedPlaylists.map(async (playlistSummary) => {
      const playlist = await playlistsApi.get(playlistSummary.id);
      const queueTracks = playlist.tracks
        .slice(0, MAX_PLAYLIST_TRACKS)
        .map(toPlaylistQueueTrack);
      const snapshot: CarPlayPlaylistSnapshot = {
        id: playlist.id,
        title: playlist.name,
        subtitle: `${playlist.tracks.length} tracks`,
        tracks: queueTracks.map(toTrackSnapshot),
      };

      return {
        id: playlist.id,
        queueTracks,
        snapshot,
      };
    }));

    const queueMap = new Map<string, Track[]>();
    for (const playlist of playlists) {
      queueMap.set(playlist.id, playlist.queueTracks);
    }

    return {
      snapshot: playlists.map((playlist) => playlist.snapshot),
      queueMap,
    };
  }

  private handleFavoriteTrackSelection(event: CarPlayFavoriteTrackSelectionEvent): void {
    const queue = this.browseCache.favoriteTracks;
    if (queue.length === 0) return;

    usePlayerStore.getState().setQueueByTrackId(queue, event.trackId, {
      type: 'other',
      id: 'carplay:favorites',
    });
  }

  private handleLibrarySelection(event: CarPlayLibrarySelectionEvent): void {
    if (event.selectionType !== 'track') return;

    let queue: Track[] = [];
    let source: QueueSource = { type: 'other', id: `carplay:${event.bucketId}` };

    if (event.bucketId === 'recently-played') {
      queue = this.browseCache.recentTracks;
      source = { type: 'other', id: 'carplay:recently-played' };
    } else if (event.bucketId === 'artists' && event.parentId) {
      queue = this.browseCache.artistTracks.get(event.parentId) ?? [];
      source = { type: 'artist', id: event.parentId };
    } else if (event.bucketId === 'albums' && event.parentId) {
      queue = this.browseCache.albumTracks.get(event.parentId) ?? [];
      source = { type: 'album', id: event.parentId };
    }

    this.playQueueSelection(queue, event.itemId, source, 'library');
  }

  private handlePlaylistSelection(_event: CarPlayPlaylistSelectionEvent): void {
    // Intentionally no-op for MVP. Native templates already drill into playlist detail locally.
  }

  private handlePlaylistTrackSelection(event: CarPlayPlaylistTrackSelectionEvent): void {
    const queue = this.browseCache.playlistTracks.get(event.playlistId) ?? [];
    this.playQueueSelection(queue, event.trackId, { type: 'playlist', id: event.playlistId }, 'playlist');
  }

  private playQueueSelection(queue: Track[], trackId: string, source: QueueSource, kind: 'library' | 'playlist'): void {
    if (queue.length === 0) {
      log.warn('Ignoring CarPlay selection without queue data', { kind, trackId, source });
      this.queueBrowseRefresh(`missing-queue:${kind}`);
      return;
    }

    const state = usePlayerStore.getState();
    state.setQueueByTrackId(queue, trackId, source);
  }

  private resetBrowseCache(): void {
    this.browseCache = {
      favoriteTracks: [],
      favoriteTrackIds: new Set(),
      recentTracks: [],
      artistTracks: new Map(),
      albumTracks: new Map(),
      playlistTracks: new Map(),
    };
  }
}

const coordinator = new CarPlayCoordinator();

export function startCarPlayCoordinator(): void {
  coordinator.start();
}
