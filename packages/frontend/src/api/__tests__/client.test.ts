/**
 * Tests for API client - HTTP request building, error handling, and response parsing.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'

// Create mock instance that will be returned by axios.create
const mockApiInstance = {
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
  head: vi.fn(),
  interceptors: {
    request: { use: vi.fn() },
    response: { use: vi.fn() },
  },
}

// Mock axios
vi.mock('axios', () => ({
  default: {
    create: vi.fn(() => mockApiInstance),
  },
}))

// Mock profile service
vi.mock('../../services/profileService', () => ({
  getSelectedProfileId: vi.fn(() => Promise.resolve('profile-123')),
  clearSelectedProfile: vi.fn(() => Promise.resolve()),
}))

describe('API client configuration', () => {
  beforeEach(async () => {
    vi.clearAllMocks()
    vi.resetModules()
  })

  it('should create axios instance with correct baseURL', async () => {
    const axios = (await import('axios')).default
    await import('../base')

    expect(axios.create).toHaveBeenCalledWith({
      baseURL: '/api/v1',
    })
  })

  it('should set up request interceptor for profile header', async () => {
    await import('../base')

    expect(mockApiInstance.interceptors.request.use).toHaveBeenCalled()
  })

  it('should set up response interceptor for error handling', async () => {
    await import('../base')

    expect(mockApiInstance.interceptors.response.use).toHaveBeenCalled()
  })
})

describe('tracksApi', () => {
  let tracksApi: typeof import('..').tracksApi

  beforeEach(async () => {
    vi.clearAllMocks()
    vi.resetModules()
    const module = await import('..')
    tracksApi = module.tracksApi
  })

  describe('getStreamUrl', () => {
    it('should return correct stream URL', () => {
      const url = tracksApi.getStreamUrl('track-123')
      expect(url).toBe('/api/v1/tracks/track-123/stream')
    })
  })

  describe('getArtworkUrl', () => {
    it('should return full size artwork URL by default', () => {
      const url = tracksApi.getArtworkUrl('track-123')
      expect(url).toBe('/api/v1/tracks/track-123/artwork?size=full')
    })

    it('should return thumbnail URL when specified', () => {
      const url = tracksApi.getArtworkUrl('track-123', 'thumb')
      expect(url).toBe('/api/v1/tracks/track-123/artwork?size=thumb')
    })
  })

  describe('list', () => {
    it('should call API with pagination params', async () => {
      mockApiInstance.get.mockResolvedValue({
        data: { tracks: [], total: 0, page: 1, page_size: 50 },
      })

      await tracksApi.list({ page: 2, page_size: 25 })

      expect(mockApiInstance.get).toHaveBeenCalledWith('/tracks', {
        params: { page: 2, page_size: 25 },
      })
    })

    it('should call API with filter params', async () => {
      mockApiInstance.get.mockResolvedValue({
        data: { tracks: [], total: 0 },
      })

      await tracksApi.list({
        artist: 'Test Artist',
        album: 'Test Album',
        genre: 'Rock',
      })

      expect(mockApiInstance.get).toHaveBeenCalledWith('/tracks', {
        params: expect.objectContaining({
          artist: 'Test Artist',
          album: 'Test Album',
          genre: 'Rock',
        }),
      })
    })
  })

  describe('getIds', () => {
    it('should request shuffled IDs', async () => {
      mockApiInstance.get.mockResolvedValue({
        data: { ids: ['id1', 'id2'], total: 2 },
      })

      await tracksApi.getIds({ shuffle: true })

      expect(mockApiInstance.get).toHaveBeenCalledWith('/tracks/ids', {
        params: { shuffle: true },
      })
    })

    it('should include start_with parameter', async () => {
      mockApiInstance.get.mockResolvedValue({
        data: { ids: ['id1', 'id2'], total: 2 },
      })

      await tracksApi.getIds({ start_with: 'track-first' })

      expect(mockApiInstance.get).toHaveBeenCalledWith('/tracks/ids', {
        params: { start_with: 'track-first' },
      })
    })
  })

  describe('getBatch', () => {
    it('should POST track IDs for batch fetch', async () => {
      mockApiInstance.post.mockResolvedValue({
        data: [{ id: 'id1' }, { id: 'id2' }],
      })

      const result = await tracksApi.getBatch(['id1', 'id2'])

      expect(mockApiInstance.post).toHaveBeenCalledWith('/tracks/batch', {
        ids: ['id1', 'id2'],
      })
      expect(result).toHaveLength(2)
    })
  })

  describe('get', () => {
    it('should fetch single track by ID', async () => {
      mockApiInstance.get.mockResolvedValue({
        data: { id: 'track-123', title: 'Test Song' },
      })

      const result = await tracksApi.get('track-123')

      expect(mockApiInstance.get).toHaveBeenCalledWith('/tracks/track-123')
      expect(result.title).toBe('Test Song')
    })
  })

  describe('getSimilar', () => {
    it('should fetch similar tracks with limit', async () => {
      mockApiInstance.get.mockResolvedValue({
        data: [{ id: 'similar-1' }],
      })

      await tracksApi.getSimilar('track-123', 5)

      expect(mockApiInstance.get).toHaveBeenCalledWith('/tracks/track-123/similar', {
        params: { limit: 5 },
      })
    })
  })
})

describe('libraryApi', () => {
  let libraryApi: typeof import('..').libraryApi

  beforeEach(async () => {
    vi.clearAllMocks()
    vi.resetModules()
    const module = await import('..')
    libraryApi = module.libraryApi
  })

  describe('getStats', () => {
    it('should fetch library statistics', async () => {
      mockApiInstance.get.mockResolvedValue({
        data: { total_tracks: 1000, total_artists: 100 },
      })

      const stats = await libraryApi.getStats()

      expect(mockApiInstance.get).toHaveBeenCalledWith('/library/stats')
      expect(stats.total_tracks).toBe(1000)
    })
  })

  describe('listArtists', () => {
    it('should list artists with sorting', async () => {
      mockApiInstance.get.mockResolvedValue({
        data: { items: [], total: 0 },
      })

      await libraryApi.listArtists({
        sort_by: 'track_count',
        page: 1,
        page_size: 50,
      })

      expect(mockApiInstance.get).toHaveBeenCalledWith('/library/artists', {
        params: {
          sort_by: 'track_count',
          page: 1,
          page_size: 50,
        },
      })
    })
  })

  describe('getArtist', () => {
    it('should encode artist name in URL', async () => {
      mockApiInstance.get.mockResolvedValue({
        data: { name: 'Artist / Name', track_count: 10 },
      })

      await libraryApi.getArtist('Artist / Name')

      // Should encode the slash (encodePathSegment double-encodes %2F → %252F)
      expect(mockApiInstance.get).toHaveBeenCalledWith(
        expect.stringContaining('Artist%20%252F%20Name'),
        expect.any(Object)
      )
    })
  })

  describe('getArtistImageUrl', () => {
    it('should return correct artist image URL', () => {
      const url = libraryApi.getArtistImageUrl('Test Artist', 'large')
      expect(url).toContain(encodeURIComponent('Test Artist'))
      expect(url).toContain('size=large')
    })
  })

  describe('sync', () => {
    it('should start library sync', async () => {
      mockApiInstance.post.mockResolvedValue({
        data: { status: 'running', message: 'Sync started' },
      })

      const result = await libraryApi.sync()

      expect(mockApiInstance.post).toHaveBeenCalledWith('/library/sync', null, {
        params: { reread_unchanged: false },
      })
      expect(result.status).toBe('running')
    })

    it('should pass reread option', async () => {
      mockApiInstance.post.mockResolvedValue({
        data: { status: 'running' },
      })

      await libraryApi.sync({ rereadUnchanged: true })

      expect(mockApiInstance.post).toHaveBeenCalledWith('/library/sync', null, {
        params: { reread_unchanged: true },
      })
    })
  })
})

describe('playlistsApi', () => {
  let playlistsApi: typeof import('..').playlistsApi

  beforeEach(async () => {
    vi.clearAllMocks()
    vi.resetModules()
    const module = await import('..')
    playlistsApi = module.playlistsApi
  })

  describe('create', () => {
    it('should create playlist with track IDs', async () => {
      mockApiInstance.post.mockResolvedValue({
        data: { id: 'pl-123', name: 'New Playlist' },
      })

      const result = await playlistsApi.create({
        name: 'New Playlist',
        track_ids: ['track-1', 'track-2'],
      })

      expect(mockApiInstance.post).toHaveBeenCalledWith('/playlists', {
        name: 'New Playlist',
        track_ids: ['track-1', 'track-2'],
      })
      expect(result.name).toBe('New Playlist')
    })
  })

  describe('addTracks', () => {
    it('should add tracks to existing playlist', async () => {
      mockApiInstance.post.mockResolvedValue({
        data: { id: 'pl-123', tracks: [] },
      })

      await playlistsApi.addTracks('pl-123', ['track-3', 'track-4'])

      expect(mockApiInstance.post).toHaveBeenCalledWith('/playlists/pl-123/tracks', [
        'track-3',
        'track-4',
      ])
    })
  })

  describe('reorderTracks', () => {
    it('should reorder playlist tracks', async () => {
      mockApiInstance.put.mockResolvedValue({
        data: { id: 'pl-123', tracks: [] },
      })

      await playlistsApi.reorderTracks('pl-123', ['track-2', 'track-1', 'track-3'])

      expect(mockApiInstance.put).toHaveBeenCalledWith('/playlists/pl-123/tracks/reorder', {
        track_ids: ['track-2', 'track-1', 'track-3'],
      })
    })
  })
})

describe('favoritesApi', () => {
  let favoritesApi: typeof import('..').favoritesApi

  beforeEach(async () => {
    vi.clearAllMocks()
    vi.resetModules()
    const module = await import('..')
    favoritesApi = module.favoritesApi
  })

  describe('toggle', () => {
    it('should toggle favorite status', async () => {
      mockApiInstance.post.mockResolvedValue({
        data: { track_id: 'track-123', is_favorite: true },
      })

      const result = await favoritesApi.toggle('track-123')

      expect(mockApiInstance.post).toHaveBeenCalledWith('/favorites/track-123/toggle')
      expect(result.is_favorite).toBe(true)
    })
  })
})

describe('Error handling', () => {
  describe('401 profile invalidation', () => {
    it('should dispatch profile-invalidated event on 401 with specific message', async () => {
      const dispatchSpy = vi.spyOn(window, 'dispatchEvent')
      vi.resetModules()

      // Import base to set up interceptors
      await import('../base')

      // Get the response interceptor error handler
      const errorHandler = mockApiInstance.interceptors.response.use.mock.calls[0][1]

      // Simulate 401 error with profile message
      const error = {
        response: {
          status: 401,
          data: { detail: 'Invalid profile, please re-register' },
        },
      }

      // The error handler should reject
      await expect(errorHandler(error)).rejects.toEqual(error)

      // Should have dispatched event
      expect(dispatchSpy).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'profile-invalidated' })
      )
    })

    it('should not dispatch event for other 401 errors', async () => {
      const dispatchSpy = vi.spyOn(window, 'dispatchEvent')
      vi.resetModules()

      await import('../base')

      const errorHandler = mockApiInstance.interceptors.response.use.mock.calls[0][1]

      // Simulate 401 error without profile message
      const error = {
        response: {
          status: 401,
          data: { detail: 'Unauthorized' },
        },
      }

      await expect(errorHandler(error)).rejects.toEqual(error)

      // Should not dispatch profile-invalidated event
      expect(dispatchSpy).not.toHaveBeenCalledWith(
        expect.objectContaining({ type: 'profile-invalidated' })
      )
    })
  })
})

describe('artworkApi', () => {
  let artworkApi: typeof import('..').artworkApi

  beforeEach(async () => {
    vi.clearAllMocks()
    vi.resetModules()
    const module = await import('..')
    artworkApi = module.artworkApi
  })

  describe('queue', () => {
    it('should queue artwork for download', async () => {
      mockApiInstance.post.mockResolvedValue({
        data: { status: 'queued', album_hash: 'abc123' },
      })

      const result = await artworkApi.queue({
        artist: 'Test Artist',
        album: 'Test Album',
      })

      expect(mockApiInstance.post).toHaveBeenCalledWith('/artwork/queue', {
        artist: 'Test Artist',
        album: 'Test Album',
      })
      expect(result.status).toBe('queued')
    })
  })

  describe('queueBatch', () => {
    it('should queue multiple artworks', async () => {
      mockApiInstance.post.mockResolvedValue({
        data: { status: 'queued', queued_count: 2 },
      })

      await artworkApi.queueBatch([
        { artist: 'Artist 1', album: 'Album 1' },
        { artist: 'Artist 2', album: 'Album 2' },
      ])

      expect(mockApiInstance.post).toHaveBeenCalledWith('/artwork/queue/batch', {
        items: [
          { artist: 'Artist 1', album: 'Album 1' },
          { artist: 'Artist 2', album: 'Album 2' },
        ],
      })
    })
  })

  describe('checkExists', () => {
    it('should return true when artwork exists', async () => {
      mockApiInstance.head.mockResolvedValue({})

      const exists = await artworkApi.checkExists('Artist', 'Album')

      expect(exists).toBe(true)
    })

    it('should return false when artwork does not exist', async () => {
      mockApiInstance.head.mockRejectedValue(new Error('404'))

      const exists = await artworkApi.checkExists('Artist', 'Album')

      expect(exists).toBe(false)
    })
  })
})

describe('exportImportApi', () => {
  let exportImportApi: typeof import('..').exportImportApi

  beforeEach(async () => {
    vi.clearAllMocks()
    vi.resetModules()
    const module = await import('..')
    exportImportApi = module.exportImportApi
  })

  describe('export', () => {
    it('should export profile data', async () => {
      mockApiInstance.post.mockResolvedValue({
        data: { version: 1, profile: {}, play_history: [] },
      })

      const result = await exportImportApi.export({
        include_play_history: true,
        include_favorites: true,
      })

      expect(mockApiInstance.post).toHaveBeenCalledWith('/export-import/export', {
        include_play_history: true,
        include_favorites: true,
      })
      expect(result.version).toBe(1)
    })
  })

  describe('previewImport', () => {
    it('should preview import file', async () => {
      mockApiInstance.post.mockResolvedValue({
        data: { session_id: 'session-123', summary: {} },
      })

      const file = new File(['{}'], 'export.json', { type: 'application/json' })
      const result = await exportImportApi.previewImport(file)

      expect(mockApiInstance.post).toHaveBeenCalledWith(
        '/export-import/import/preview',
        expect.any(FormData),
        { headers: { 'Content-Type': 'multipart/form-data' } }
      )
      expect(result.session_id).toBe('session-123')
    })
  })
})

describe('profilesApi', () => {
  let profilesApi: typeof import('..').profilesApi

  beforeEach(async () => {
    vi.clearAllMocks()
    vi.resetModules()
    const module = await import('..')
    profilesApi = module.profilesApi
  })

  describe('list', () => {
    it('should list all profiles', async () => {
      mockApiInstance.get.mockResolvedValue({
        data: [
          { id: 'p1', name: 'User 1' },
          { id: 'p2', name: 'User 2' },
        ],
      })

      const profiles = await profilesApi.list()

      expect(mockApiInstance.get).toHaveBeenCalledWith('/profiles')
      expect(profiles).toHaveLength(2)
    })
  })

  describe('create', () => {
    it('should create a new profile', async () => {
      mockApiInstance.post.mockResolvedValue({
        data: { id: 'p-new', name: 'New User', color: '#ff0000' },
      })

      const result = await profilesApi.create({ name: 'New User', color: '#ff0000' })

      expect(mockApiInstance.post).toHaveBeenCalledWith('/profiles', {
        name: 'New User',
        color: '#ff0000',
      })
      expect(result.name).toBe('New User')
    })
  })

  describe('getAvatarUrl', () => {
    it('should return correct avatar URL', () => {
      const url = profilesApi.getAvatarUrl('profile-123')
      expect(url).toBe('/api/v1/profiles/profile-123/avatar')
    })
  })
})

describe('smartPlaylistsApi', () => {
  let smartPlaylistsApi: typeof import('..').smartPlaylistsApi

  beforeEach(async () => {
    vi.clearAllMocks()
    vi.resetModules()
    const module = await import('..')
    smartPlaylistsApi = module.smartPlaylistsApi
  })

  describe('create', () => {
    it('should create smart playlist with rules', async () => {
      mockApiInstance.post.mockResolvedValue({
        data: { id: 'sp-123', name: 'High Energy', rules: [] },
      })

      const result = await smartPlaylistsApi.create({
        name: 'High Energy',
        rules: [{ field: 'energy', operator: '>', value: 0.8 }],
        match_mode: 'all',
      })

      expect(mockApiInstance.post).toHaveBeenCalledWith('/smart-playlists', {
        name: 'High Energy',
        rules: [{ field: 'energy', operator: '>', value: 0.8 }],
        match_mode: 'all',
      })
      expect(result.name).toBe('High Energy')
    })
  })

  describe('refresh', () => {
    it('should refresh smart playlist tracks', async () => {
      mockApiInstance.post.mockResolvedValue({
        data: { id: 'sp-123', cached_track_count: 25 },
      })

      await smartPlaylistsApi.refresh('sp-123')

      expect(mockApiInstance.post).toHaveBeenCalledWith('/smart-playlists/sp-123/refresh')
    })
  })
})

