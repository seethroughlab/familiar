/**
 * Tests for IndexedDB database (Dexie) - offline storage and data persistence.
 *
 * These tests verify the database types and structure without requiring
 * actual IndexedDB, using fake-indexeddb for the mock environment.
 */
import { describe, it, expect } from 'vitest'

// Test type definitions are correct
describe('FamiliarDB types', () => {
  it('should export all required interfaces', async () => {
    const module = await import('../index')

    // db should be exported
    expect(module.db).toBeDefined()
    expect(module.FamiliarDB).toBeDefined()
    expect(module.isIndexedDBAvailable).toBeDefined()
  })

  it('should have all expected table properties on db', async () => {
    const { db } = await import('../index')

    // Verify table definitions exist (they may be undefined in test environment
    // but the properties should be declared)
    expect('deviceProfile' in db).toBe(true)
    expect('chatSessions' in db).toBe(true)
    expect('cachedTracks' in db).toBe(true)
    expect('offlineTracks' in db).toBe(true)
    expect('offlineArtwork' in db).toBe(true)
    expect('pendingActions' in db).toBe(true)
    expect('playerState' in db).toBe(true)
    expect('cachedProfiles' in db).toBe(true)
    expect('cachedPlaylists' in db).toBe(true)
    expect('cachedSmartPlaylists' in db).toBe(true)
    expect('cachedFavorites' in db).toBe(true)
    expect('downloadQueue' in db).toBe(true)
    expect('partialDownloads' in db).toBe(true)
  })
})

describe('isIndexedDBAvailable', () => {
  it('should be a function', async () => {
    const { isIndexedDBAvailable } = await import('../index')
    expect(typeof isIndexedDBAvailable).toBe('function')
  })

  it('should return a promise', async () => {
    const { isIndexedDBAvailable } = await import('../index')
    const result = isIndexedDBAvailable()
    expect(result).toBeInstanceOf(Promise)
  })
})

// Test interface shapes match expected structure
describe('Interface type validation', () => {
  it('DeviceProfile should have correct shape', () => {
    // TypeScript compile-time check - if this compiles, types are correct
    const profile: import('../index').DeviceProfile = {
      id: 'device-profile',
      profileId: 'profile-123',
      deviceId: 'device-456',
      createdAt: new Date(),
    }

    expect(profile.id).toBe('device-profile')
    expect(profile.profileId).toBe('profile-123')
    expect(profile.deviceId).toBe('device-456')
    expect(profile.createdAt).toBeInstanceOf(Date)
  })

  it('ChatMessage should have correct shape', () => {
    const message: import('../index').ChatMessage = {
      id: 'msg-1',
      role: 'user',
      content: 'Hello',
      timestamp: new Date(),
    }

    expect(message.role).toBe('user')
    expect(message.content).toBe('Hello')
  })

  it('ChatMessage should support tool calls', () => {
    const message: import('../index').ChatMessage = {
      id: 'msg-2',
      role: 'assistant',
      content: 'Searching...',
      toolCalls: [
        {
          name: 'search_library',
          input: { query: 'jazz' },
          result: { tracks: [], count: 0 },
          status: 'complete',
        },
      ],
      timestamp: new Date(),
    }

    expect(message.toolCalls).toHaveLength(1)
    expect(message.toolCalls![0].name).toBe('search_library')
  })

  it('ChatSession should have correct shape', () => {
    const session: import('../index').ChatSession = {
      id: 'session-123',
      profileId: 'profile-456',
      title: 'Test Chat',
      messages: [],
      createdAt: new Date(),
      updatedAt: new Date(),
    }

    expect(session.title).toBe('Test Chat')
    expect(session.messages).toHaveLength(0)
  })

  it('CachedTrack should handle nullable fields', () => {
    const track: import('../index').CachedTrack = {
      id: 'track-123',
      title: 'Test Song',
      artist: 'Test Artist',
      album: 'Test Album',
      albumArtist: null,
      genre: null,
      year: null,
      durationSeconds: null,
      trackNumber: null,
      discNumber: null,
      cachedAt: new Date(),
    }

    expect(track.title).toBe('Test Song')
    expect(track.albumArtist).toBeNull()
    expect(track.genre).toBeNull()
  })

  it('OfflineTrack should hold audio blob', () => {
    const audioBlob = new Blob(['fake audio data'], { type: 'audio/mp3' })
    const offlineTrack: import('../index').OfflineTrack = {
      id: 'track-123',
      audio: audioBlob,
      cachedAt: new Date(),
    }

    expect(offlineTrack.audio).toBeInstanceOf(Blob)
    expect(offlineTrack.audio.type).toBe('audio/mp3')
  })

  it('OfflineArtwork should use hash as key', () => {
    const artworkBlob = new Blob(['fake image data'], { type: 'image/jpeg' })
    const artwork: import('../index').OfflineArtwork = {
      hash: 'album-hash-123',
      artwork: artworkBlob,
      cachedAt: new Date(),
    }

    expect(artwork.hash).toBe('album-hash-123')
    expect(artwork.artwork).toBeInstanceOf(Blob)
  })

  it('PendingAction should support different action types', () => {
    const scrobbleAction: import('../index').PendingAction = {
      id: 1,
      profileId: 'profile-123',
      type: 'scrobble',
      payload: { track_id: 'track-456', timestamp: Date.now() },
      createdAt: new Date(),
      retries: 0,
    }

    expect(scrobbleAction.type).toBe('scrobble')

    const favoriteAction: import('../index').PendingAction = {
      id: 2,
      profileId: 'profile-123',
      type: 'favorite_toggle',
      payload: { track_id: 'track-789' },
      createdAt: new Date(),
      retries: 0,
    }

    expect(favoriteAction.type).toBe('favorite_toggle')
  })

  it('PersistedPlayerState should have all player state fields', () => {
    const state: import('../index').PersistedPlayerState = {
      id: 'profile-123',
      volume: 0.8,
      shuffle: true,
      repeat: 'all',
      queueTrackIds: ['track-1', 'track-2', 'track-3'],
      queueIndex: 1,
      currentTrackId: 'track-2',
      shuffleOrder: [1, 2, 0],
      shuffleIndex: 0,
      currentTime: 42.5,
      updatedAt: new Date(),
    }

    expect(state.volume).toBe(0.8)
    expect(state.shuffle).toBe(true)
    expect(state.repeat).toBe('all')
    expect(state.queueTrackIds).toHaveLength(3)
    expect(state.currentTime).toBe(42.5)
  })

  it('CachedPlaylist should have track IDs', () => {
    const playlist: import('../index').CachedPlaylist = {
      id: 'playlist-123',
      name: 'My Favorites',
      description: 'Best songs',
      is_auto_generated: false,
      generation_prompt: null,
      track_ids: ['track-1', 'track-2'],
      track_count: 2,
      cachedAt: new Date(),
    }

    expect(playlist.name).toBe('My Favorites')
    expect(playlist.track_ids).toHaveLength(2)
  })

  it('CachedSmartPlaylist should have rules', () => {
    const smartPlaylist: import('../index').CachedSmartPlaylist = {
      id: 'smart-123',
      name: 'Recent Favorites',
      description: 'Recently favorited tracks',
      rules: [
        { field: 'is_favorite', operator: 'equals', value: true },
      ],
      match_mode: 'all',
      order_by: 'favorited_at',
      order_direction: 'desc',
      max_tracks: 50,
      track_ids: ['track-1'],
      cached_track_count: 1,
      last_refreshed_at: new Date().toISOString(),
      cachedAt: new Date(),
    }

    expect(smartPlaylist.rules).toHaveLength(1)
    expect(smartPlaylist.match_mode).toBe('all')
  })

  it('CachedFavorites should store track IDs by profile', () => {
    const favorites: import('../index').CachedFavorites = {
      profileId: 'profile-123',
      trackIds: ['track-1', 'track-2', 'track-3'],
      cachedAt: new Date(),
    }

    expect(favorites.profileId).toBe('profile-123')
    expect(favorites.trackIds).toHaveLength(3)
  })

  it('PersistedDownloadJob should track download progress', () => {
    const job: import('../index').PersistedDownloadJob = {
      id: 'playlist-123',
      type: 'playlist',
      name: 'My Playlist',
      trackIds: ['track-1', 'track-2', 'track-3'],
      completedIds: ['track-1'],
      failedIds: [],
      status: 'downloading',
      startedAt: new Date(),
      updatedAt: new Date(),
    }

    expect(job.status).toBe('downloading')
    expect(job.completedIds).toHaveLength(1)

    // Calculate progress
    const processed = job.completedIds.length + job.failedIds.length
    expect(processed).toBe(1)
  })

  it('PartialDownload should support resume', () => {
    const partial: import('../index').PartialDownload = {
      trackId: 'track-123',
      bytesDownloaded: 1024 * 1024, // 1MB
      totalBytes: 5 * 1024 * 1024, // 5MB
      chunks: [new Blob(['chunk1']), new Blob(['chunk2'])],
      updatedAt: new Date(),
    }

    expect(partial.chunks).toHaveLength(2)
    expect(partial.bytesDownloaded).toBeLessThan(partial.totalBytes)
  })

  it('CachedProfile should have service integration flags', () => {
    const profile: import('../index').CachedProfile = {
      id: 'profile-123',
      name: 'Test User',
      color: '#ff0000',
      avatar_url: null,
      has_spotify: true,
      has_lastfm: false,
      cachedAt: new Date(),
    }

    expect(profile.has_spotify).toBe(true)
    expect(profile.has_lastfm).toBe(false)
  })
})

describe('FamiliarDB class', () => {
  it('should extend Dexie', async () => {
    const { FamiliarDB } = await import('../index')
    const Dexie = (await import('dexie')).default

    const db = new FamiliarDB()
    expect(db).toBeInstanceOf(Dexie)
  })

  it('should define database name', async () => {
    const { db } = await import('../index')
    expect(db.name).toBe('FamiliarDB')
  })
})
