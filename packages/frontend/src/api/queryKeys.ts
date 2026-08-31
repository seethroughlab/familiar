/**
 * Centralized query key factory for React Query.
 *
 * Uses the TkDodo factory pattern so every query key is defined once
 * and referenced everywhere via `queryKeys.<entity>.<scope>(...)`.
 *
 * Migrated families: playlists, playlist, tracks, trackMetadata, album, smartPlaylists.
 * Remaining families are included for completeness and will be migrated incrementally.
 */
export const queryKeys = {
  // ── Tracks ────────────────────────────────────────────────────────────
  tracks: {
    all: ['tracks'] as const,
    list: (filters: Record<string, unknown>) => ['tracks', filters] as const,
  },
  trackMetadata: {
    all: ['track-metadata'] as const,
    detail: (trackId: string) => ['track-metadata', trackId] as const,
  },
  trackCommonValues: {
    all: ['track-common-values'] as const,
    detail: (selectedIds: string | string[]) => ['track-common-values', selectedIds] as const,
  },
  trackDiscover: {
    detail: (trackId: string) => ['track-discover', trackId] as const,
  },

  // ── Library ───────────────────────────────────────────────────────────
  library: {
    stats: () => ['library', 'stats'] as const,
    playStats: (limit: number) => ['library', 'play-stats', limit] as const,
    // Its own key, not part of `stats`: coverage stats one file per album (~4k on Jeff's library),
    // and the dashboard should not pay for a filesystem sweep on every load.
    artworkCoverage: () => ['library', 'artwork-coverage'] as const,
  },

  // ── Albums ────────────────────────────────────────────────────────────
  albums: {
    all: ['library-albums'] as const,
    list: (filters: Record<string, unknown>) => ['library-albums', filters] as const,
  },
  album: {
    all: ['album'] as const,
    detail: (artist: string, album: string) => ['album', artist, album] as const,
  },

  // ── Artists ───────────────────────────────────────────────────────────
  artists: {
    all: ['library-artists'] as const,
    list: (filters: Record<string, unknown>) => ['library-artists', filters] as const,
  },
  artist: {
    detail: (name: string) => ['artist', name] as const,
  },
  artistsPicker: {
    search: (query: string) => ['artists-picker', query] as const,
  },

  // ── Playlists ─────────────────────────────────────────────────────────
  playlists: {
    all: ['playlists'] as const,
    ai: ['playlists', 'ai'] as const,
  },
  playlist: {
    all: ['playlist'] as const,
    detail: (id: string) => ['playlist', id] as const,
  },
  playlistRecommendations: {
    detail: (id: string) => ['playlist-recommendations', id] as const,
  },

  // ── Smart Playlists ───────────────────────────────────────────────────
  smartPlaylists: {
    all: ['smart-playlists'] as const,
    fields: ['smart-playlist-fields'] as const,
  },
  smartPlaylist: {
    all: ['smart-playlist'] as const,
    detail: (id: string) => ['smart-playlist', id] as const,
  },
  smartPlaylistTracks: {
    detail: (id: string) => ['smart-playlist-tracks', id] as const,
  },

  // ── Mix Tapes ─────────────────────────────────────────────────────────
  mixtapes: {
    all: ['mixtapes'] as const,
    detail: (id: string) => ['mixtape', id] as const,
  },

  // ── Favorites ─────────────────────────────────────────────────────────
  favorites: {
    all: ['favorites'] as const,
    autoDownload: ['favorites-auto-download'] as const,
  },

  // ── Health ────────────────────────────────────────────────────────────
  discoverySources: {
    all: ['discovery-sources'] as const,
  },

  // ── Settings & Config ─────────────────────────────────────────────────
  appSettings: {
    all: ['app-settings'] as const,
  },
  lastfmStatus: {
    all: ['lastfm-status'] as const,
  },

  // ── Discovery & Browse ────────────────────────────────────────────────
  libraryDiscover: {
    all: ['library-discover'] as const,
  },
  newReleases: {
    all: ['new-releases'] as const,
    list: (params: { limit: number; offset: number; include_dismissed: boolean; include_owned: boolean }) =>
      ['new-releases', 'list', params] as const,
    status: ['new-releases', 'status'] as const,
  },
  listeningProfileAlbums: {
    all: ['listening-profile-albums'] as const,
    list: (params: { limit: number }) =>
      ['listening-profile-albums', 'list', params] as const,
  },
  playlistExternalAlbums: {
    all: ['playlist-external-albums'] as const,
    forPlaylist: (playlistId: string) => ['playlist-external-albums', playlistId] as const,
  },
  libraryMoodDistribution: {
    detail: (xAxis: string, yAxis: string) => ['library-mood-distribution', xAxis, yAxis] as const,
  },
  letterIndex: {
    detail: (...args: string[]) => ['letter-index', ...args] as const,
  },
  ambientSeedSearch: {
    search: (query: string) => ['ambient-seed-search', query] as const,
  },
  egoMap: {
    detail: (artist: string) => ['ego-map', artist] as const,
  },

  // ── Pending Review ──────────────────────────────────────────────────
  pendingTracks: {
    all: ['pending-tracks'] as const,
    groups: (params?: Record<string, unknown>) => ['pending-tracks', 'groups', params] as const,
    stats: ['pending-tracks', 'stats'] as const,
  },

  // ── Proposed Changes ──────────────────────────────────────────────────
  proposedChanges: {
    all: ['proposed-changes'] as const,
    list: (statusFilter: string | null) => ['proposed-changes', statusFilter] as const,
    stats: ['proposed-changes-stats'] as const,
  },

  // ── Video ─────────────────────────────────────────────────────────────
  videoStatus: {
    detail: (trackId: string) => ['video-status', trackId] as const,
  },
  videoSearch: {
    detail: (trackId: string) => ['video-search', trackId] as const,
  },

  // ── Misc ──────────────────────────────────────────────────────────────
  bulkIdentify: {
    detail: (taskId: string) => ['bulk-identify', taskId] as const,
  },
  organizeTemplates: {
    all: ['organize-templates'] as const,
  },
} as const;
