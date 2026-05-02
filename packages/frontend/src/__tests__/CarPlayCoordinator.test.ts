import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const listeners = new Map<string, (data?: unknown) => void>();

const syncCarPlayLibrary = vi.fn();
const syncCarPlayFavorites = vi.fn();
const syncCarPlayPlaylists = vi.fn();
const syncCarPlayNowPlaying = vi.fn();
const clearCarPlayState = vi.fn();

let playerState: {
  currentTrack: Record<string, unknown> | null;
  isPlaying: boolean;
  setQueueByTrackId: ReturnType<typeof vi.fn>;
};
let storeListeners: Set<() => void>;

const mockGetSelectedProfileId = vi.fn();
const mockListFavorites = vi.fn();
const mockGetCachedFavorites = vi.fn();
const mockResolveTrackIds = vi.fn();
const mockPlayTrackingGetStats = vi.fn();
const mockTracksList = vi.fn();
const mockTracksGetBatch = vi.fn();
const mockTracksGetArtworkUrl = vi.fn((trackId: string) => `artwork://${trackId}`);
const mockListArtists = vi.fn();
const mockGetArtist = vi.fn();
const mockListAlbums = vi.fn();
const mockGetAlbum = vi.fn();
const mockListPlaylists = vi.fn();
const mockGetPlaylist = vi.fn();

vi.mock('../../../ios/src/plugins/familiarAudio', () => ({
  FamiliarAudio: {
    addListener: vi.fn(async (event: string, handler: (data?: unknown) => void) => {
      listeners.set(event, handler);
      return {
        remove: vi.fn(async () => {
          listeners.delete(event);
        }),
      };
    }),
    syncCarPlayFavorites,
    syncCarPlayLibrary,
    syncCarPlayPlaylists,
    syncCarPlayNowPlaying,
    clearCarPlayState,
  },
}));

vi.mock('../player/playerStore', () => ({
  usePlayerStore: Object.assign(vi.fn(), {
    subscribe: (listener: () => void) => {
      storeListeners.add(listener);
      return () => {
        storeListeners.delete(listener);
      };
    },
    getState: () => playerState,
  }),
}));

vi.mock('../services/profileSelection', () => ({
  getSelectedProfileId: mockGetSelectedProfileId,
}));

vi.mock('../services/playlistCache', () => ({
  getCachedFavorites: mockGetCachedFavorites,
  resolveTrackIds: mockResolveTrackIds,
}));

vi.mock('../api', () => ({
  favoritesApi: {
    list: mockListFavorites,
  },
  libraryApi: {
    listArtists: mockListArtists,
    getArtist: mockGetArtist,
    listAlbums: mockListAlbums,
    getAlbum: mockGetAlbum,
  },
  playlistsApi: {
    list: mockListPlaylists,
    get: mockGetPlaylist,
  },
  playTrackingApi: {
    getStats: mockPlayTrackingGetStats,
  },
  tracksApi: {
    list: mockTracksList,
    getBatch: mockTracksGetBatch,
    getArtworkUrl: mockTracksGetArtworkUrl,
  },
  getApiOrigin: () => 'http://test.local',
}));

vi.mock('../utils/logger', () => ({
  createLogger: () => ({
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  }),
}));

function flushPromises(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

function notifyStore(): void {
  for (const listener of storeListeners) {
    listener();
  }
}

describe('CarPlayCoordinator', () => {
  beforeEach(() => {
    listeners.clear();
    syncCarPlayFavorites.mockReset();
    syncCarPlayLibrary.mockReset();
    syncCarPlayPlaylists.mockReset();
    syncCarPlayNowPlaying.mockReset();
    clearCarPlayState.mockReset();

    playerState = {
      currentTrack: null,
      isPlaying: false,
      setQueueByTrackId: vi.fn(),
    };
    storeListeners = new Set();

    mockGetSelectedProfileId.mockReset().mockResolvedValue('profile-1');
    mockListFavorites.mockReset().mockResolvedValue({
      favorites: [
        {
          id: 'favorite-1',
          file_path: '',
          title: 'Favorite One',
          artist: 'Luna',
          album: 'Night Drive',
          album_artist: 'Luna',
          album_type: 'album',
          track_number: 1,
          disc_number: 1,
          year: 2025,
          genre: 'Synth',
          duration_seconds: 215,
          format: 'flac',
          analysis_version: 1,
          favorited_at: '2026-04-30T00:00:00Z',
          play_count: 3,
          last_played_at: null,
        },
      ],
      total: 1,
    });
    mockGetCachedFavorites.mockReset().mockResolvedValue(undefined);
    mockResolveTrackIds.mockReset().mockResolvedValue([]);
    mockPlayTrackingGetStats.mockReset().mockResolvedValue({
      top_tracks: [
        { id: 'recent-1' },
        { id: 'recent-2' },
      ],
    });
    mockTracksList.mockReset().mockResolvedValue({
      items: [
        {
          id: 'played-1',
          file_path: '',
          title: 'Played One',
          artist: 'Artist Recent',
          album: 'Latest',
          album_artist: 'Artist Recent',
          album_type: 'album',
          track_number: 1,
          disc_number: 1,
          year: 2024,
          genre: 'Electronic',
          duration_seconds: 180,
          format: 'mp3',
          analysis_version: 1,
          last_played_at: '2026-05-02T10:00:00Z',
        },
        {
          id: 'played-2',
          file_path: '',
          title: 'Played Two',
          artist: 'Artist Recent',
          album: 'Latest',
          album_artist: 'Artist Recent',
          album_type: 'album',
          track_number: 2,
          disc_number: 1,
          year: 2024,
          genre: 'Electronic',
          duration_seconds: 200,
          format: 'mp3',
          analysis_version: 1,
          last_played_at: '2026-05-02T09:00:00Z',
        },
        {
          id: 'played-3',
          file_path: '',
          title: 'Played Three',
          artist: 'Artist Earlier',
          album: 'Earlier',
          album_artist: 'Artist Earlier',
          album_type: 'album',
          track_number: 1,
          disc_number: 1,
          year: 2023,
          genre: 'Rock',
          duration_seconds: 220,
          format: 'mp3',
          analysis_version: 1,
          last_played_at: '2026-05-02T08:00:00Z',
        },
      ],
      total: 3,
      page: 1,
      page_size: 100,
    });
    mockTracksGetBatch.mockReset().mockResolvedValue([
      {
        id: 'recent-1',
        file_path: '',
        title: 'Recent One',
        artist: 'Alpha',
        album: 'First',
        album_artist: 'Alpha',
        album_type: 'album',
        track_number: 1,
        disc_number: 1,
        year: 2024,
        genre: 'Electronic',
        duration_seconds: 180,
        format: 'mp3',
        analysis_version: 1,
      },
      {
        id: 'recent-2',
        file_path: '',
        title: 'Recent Two',
        artist: 'Beta',
        album: 'Second',
        album_artist: 'Beta',
        album_type: 'album',
        track_number: 2,
        disc_number: 1,
        year: 2023,
        genre: 'Rock',
        duration_seconds: 210,
        format: 'mp3',
        analysis_version: 1,
      },
    ]);
    mockListArtists.mockReset().mockResolvedValue({
      items: [
        { name: 'Artist One', track_count: 3, album_count: 1, first_track_id: 'artist-track-1', first_album: 'Artist Album' },
      ],
    });
    mockGetArtist.mockReset().mockImplementation(async (artistName: string) => ({
      name: artistName,
      track_count: artistName === 'Artist Recent' ? 5 : 3,
      tracks: [
        {
          id: artistName === 'Artist Recent' ? 'artist-track-recent' : 'artist-track-earlier',
          title: artistName === 'Artist Recent' ? 'Recent Artist Track' : 'Earlier Artist Track',
          album: artistName === 'Artist Recent' ? 'Latest' : 'Earlier',
          track_number: 1,
          duration_seconds: 200,
          year: 2022,
        },
      ],
    }));
    mockListAlbums.mockReset().mockResolvedValue({
      items: [
        { name: 'Album One', artist: 'Artist One', year: 2024, track_count: 2, first_track_id: 'album-track-1' },
      ],
    });
    mockGetAlbum.mockReset().mockResolvedValue({
      name: 'Album One',
      artist: 'Artist One',
      album_artist: 'Artist One',
      year: 2024,
      genre: 'Ambient',
      tracks: [
        { id: 'album-track-1', title: 'Album Track', track_number: 1, disc_number: 1, duration_seconds: 240 },
      ],
    });
    mockListPlaylists.mockReset().mockResolvedValue([
      {
        id: 'playlist-1',
        name: 'Road Trip',
      },
    ]);
    mockGetPlaylist.mockReset().mockResolvedValue({
      id: 'playlist-1',
      name: 'Road Trip',
      tracks: [
        {
          id: 'playlist-track-1',
          playlist_track_id: 'pt-1',
          type: 'local',
          title: 'Playlist Track',
          artist: 'Gamma',
          album: 'Drive',
          duration_seconds: 300,
          position: 1,
          format: 'aac',
          year: 2021,
          genre: 'Pop',
          track_number: 1,
          disc_number: 1,
          album_artist: 'Gamma',
          album_type: 'album',
          analysis_version: 2,
          play_count: 4,
          last_played_at: null,
        },
      ],
    });
  });

  afterEach(() => {
    vi.resetModules();
  });

  it('builds and syncs the expected browse snapshots on startup', async () => {
    const { startCarPlayCoordinator } = await import('../../../ios/src/CarPlayCoordinator');

    startCarPlayCoordinator();
    await flushPromises();

    expect(syncCarPlayLibrary).toHaveBeenCalledTimes(1);
    expect(syncCarPlayFavorites).toHaveBeenCalledTimes(1);
    expect(syncCarPlayPlaylists).toHaveBeenCalledTimes(1);

    const favoritesSnapshot = JSON.parse(syncCarPlayFavorites.mock.calls[0][0].snapshot) as Array<Record<string, unknown>>;
    expect(favoritesSnapshot[0].id).toBe('favorite-1');

    const librarySnapshot = JSON.parse(syncCarPlayLibrary.mock.calls[0][0].snapshot) as Array<Record<string, unknown>>;
    expect(librarySnapshot.map((bucket) => bucket.id)).toEqual([
      'recently-played',
      'artists',
      'albums',
    ]);
    expect((librarySnapshot[0].tracks as Array<Record<string, unknown>>)[0].id).toBe('recent-1');

    const playlistSnapshot = JSON.parse(syncCarPlayPlaylists.mock.calls[0][0].snapshot) as Array<Record<string, unknown>>;
    expect(playlistSnapshot[0].id).toBe('playlist-1');
    expect((playlistSnapshot[0].tracks as Array<Record<string, unknown>>)[0].id).toBe('playlist-track-1');

    expect(mockListAlbums).toHaveBeenCalledWith({
      page_size: 40,
    });
    expect(mockTracksList).toHaveBeenCalledWith({
      page: 1,
      page_size: 100,
      sort_by: 'lastPlayed',
      sort_order: 'desc',
    });
    const artistCollections = librarySnapshot[1].collections as Array<Record<string, unknown>>;
    expect(artistCollections.map((artist) => artist.id)).toEqual([
      'Artist Recent',
      'Artist Earlier',
    ]);
  });

  it('refreshes browse state again when CarPlay connects', async () => {
    const { startCarPlayCoordinator } = await import('../../../ios/src/CarPlayCoordinator');

    startCarPlayCoordinator();
    await flushPromises();
    syncCarPlayFavorites.mockClear();
    syncCarPlayLibrary.mockClear();
    syncCarPlayPlaylists.mockClear();

    listeners.get('carPlayConnected')?.();
    await flushPromises();

    expect(syncCarPlayFavorites).toHaveBeenCalledTimes(1);
    expect(syncCarPlayLibrary).toHaveBeenCalledTimes(1);
    expect(syncCarPlayPlaylists).toHaveBeenCalledTimes(1);
  });

  it('maps favorite track selections to a favorites queue', async () => {
    const { startCarPlayCoordinator } = await import('../../../ios/src/CarPlayCoordinator');

    startCarPlayCoordinator();
    await flushPromises();

    listeners.get('carPlaySelectFavoriteTrack')?.({
      trackId: 'favorite-1',
    });

    expect(playerState.setQueueByTrackId).toHaveBeenCalledWith(
      expect.arrayContaining([
        expect.objectContaining({
          id: 'favorite-1',
          title: 'Favorite One',
        }),
      ]),
      'favorite-1',
      { type: 'other', id: 'carplay:favorites' },
    );
  });

  it('falls back to cached favorites when the live favorites response is unexpectedly empty', async () => {
    mockListFavorites.mockResolvedValue({
      favorites: [],
      total: 1685,
    });
    mockGetCachedFavorites.mockResolvedValue({
      profileId: 'profile-1',
      trackIds: ['cached-favorite-1', 'cached-favorite-2'],
      cachedAt: new Date('2026-05-02T12:00:00Z'),
    });
    mockResolveTrackIds.mockResolvedValue([
      {
        id: 'cached-favorite-1',
        title: 'Cached Favorite',
        artist: 'Cache Artist',
        album: 'Cache Album',
        albumArtist: 'Cache Artist',
        genre: 'Ambient',
        year: 2020,
        durationSeconds: 222,
        trackNumber: 1,
        discNumber: 1,
        cachedAt: new Date('2026-05-02T12:00:00Z'),
      },
    ]);

    const { startCarPlayCoordinator } = await import('../../../ios/src/CarPlayCoordinator');

    startCarPlayCoordinator();
    await flushPromises();

    const favoritesSnapshot = JSON.parse(syncCarPlayFavorites.mock.calls[0][0].snapshot) as Array<Record<string, unknown>>;
    expect(favoritesSnapshot).toEqual([
      expect.objectContaining({
        id: 'cached-favorite-1',
        title: 'Cached Favorite',
      }),
    ]);
    expect(mockGetCachedFavorites).toHaveBeenCalledWith('profile-1');
    expect(mockResolveTrackIds).toHaveBeenCalledWith(['cached-favorite-1', 'cached-favorite-2']);
  });

  it('falls back to track-count artists when there is no recent play history', async () => {
    mockTracksList.mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 100,
    });
    mockListArtists.mockResolvedValue({
      items: [
        { name: 'Artist One', track_count: 3, album_count: 1, first_track_id: 'artist-track-1', first_album: 'Artist Album' },
      ],
    });

    const { startCarPlayCoordinator } = await import('../../../ios/src/CarPlayCoordinator');

    startCarPlayCoordinator();
    await flushPromises();

    expect(mockListArtists).toHaveBeenCalledWith({
      sort_by: 'track_count',
      page_size: 20,
    });
    const librarySnapshot = JSON.parse(syncCarPlayLibrary.mock.calls[0][0].snapshot) as Array<Record<string, unknown>>;
    const artistCollections = librarySnapshot[1].collections as Array<Record<string, unknown>>;
    expect(artistCollections.map((artist) => artist.id)).toEqual(['Artist One']);
  });

  it('maps playlist track selections to the shared queue actions', async () => {
    const { startCarPlayCoordinator } = await import('../../../ios/src/CarPlayCoordinator');

    startCarPlayCoordinator();
    await flushPromises();

    listeners.get('carPlaySelectPlaylistTrack')?.({
      playlistId: 'playlist-1',
      trackId: 'playlist-track-1',
    });

    expect(playerState.setQueueByTrackId).toHaveBeenCalledWith(
      expect.arrayContaining([
        expect.objectContaining({
          id: 'playlist-track-1',
          title: 'Playlist Track',
        }),
      ]),
      'playlist-track-1',
      { type: 'playlist', id: 'playlist-1' },
    );
  });

  it('still syncs surviving snapshots when one builder rejects', async () => {
    mockListAlbums.mockRejectedValue(new Error('boom: albums backend down'));

    const { startCarPlayCoordinator } = await import('../../../ios/src/CarPlayCoordinator');

    startCarPlayCoordinator();
    await flushPromises();

    expect(syncCarPlayFavorites).toHaveBeenCalledTimes(1);
    expect(syncCarPlayLibrary).toHaveBeenCalledTimes(1);
    expect(syncCarPlayPlaylists).toHaveBeenCalledTimes(1);

    const librarySnapshot = JSON.parse(syncCarPlayLibrary.mock.calls[0][0].snapshot) as Array<Record<string, unknown>>;
    expect(librarySnapshot.map((bucket) => bucket.id)).toEqual([
      'recently-played',
      'artists',
      'albums',
    ]);
    const albumsBucket = librarySnapshot[2];
    expect(albumsBucket.collections).toEqual([]);

    const favoritesSnapshot = JSON.parse(syncCarPlayFavorites.mock.calls[0][0].snapshot) as Array<Record<string, unknown>>;
    expect(favoritesSnapshot[0].id).toBe('favorite-1');
  });

  it('syncs now playing when the current track changes', async () => {
    const { startCarPlayCoordinator } = await import('../../../ios/src/CarPlayCoordinator');

    startCarPlayCoordinator();
    await flushPromises();
    syncCarPlayNowPlaying.mockClear();

    playerState.currentTrack = {
      id: 'favorite-1',
      title: 'Favorite One',
      artist: 'Luna',
      album: 'Night Drive',
    };
    playerState.isPlaying = true;
    notifyStore();
    await flushPromises();

    expect(syncCarPlayNowPlaying).toHaveBeenCalledTimes(1);
    const payload = JSON.parse(syncCarPlayNowPlaying.mock.calls[0][0].snapshot) as Record<string, unknown>;
    expect(payload.trackId).toBe('favorite-1');
    expect(payload.isPlaying).toBe(true);
    expect(payload.title).toBe('Favorite One');
    expect(payload.isFavorite).toBe(true);
  });
});
