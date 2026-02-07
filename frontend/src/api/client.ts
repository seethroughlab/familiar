import axios from 'axios';
import type { Track, TrackListResponse, LibraryStats } from '../types';
import { getSelectedProfileId, clearSelectedProfile } from '../services/profileService';
import { apiErrorTracker, extractAxiosError } from '../utils/apiErrorTracker';

const api = axios.create({
  baseURL: '/api/v1',
});

// Add X-Profile-ID header to all requests (if a profile is selected)
api.interceptors.request.use(async (config) => {
  try {
    const profileId = await getSelectedProfileId();
    if (profileId) {
      config.headers['X-Profile-ID'] = profileId;
    }
  } catch (error) {
    // Log but don't block requests if profile check fails
    console.error('Failed to get profile ID:', error);
  }
  return config;
});

// Handle 401 errors and track all API errors for debugging
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    // Track error for debugging visibility
    const errorInfo = extractAxiosError(error);
    apiErrorTracker.track(errorInfo);

    // Check if this is an "invalid profile" error
    if (
      error.response?.status === 401 &&
      (error.response?.data?.detail?.includes('re-register') ||
       error.response?.data?.detail?.includes('Invalid profile'))
    ) {
      // Clear the invalid profile selection
      await clearSelectedProfile();
      // The app should redirect to profile selector
      // Dispatch a custom event that App.tsx can listen for
      window.dispatchEvent(new CustomEvent('profile-invalidated'));
    }

    return Promise.reject(error);
  }
);

// Legacy aliases for backwards compatibility
export const getOrCreateDeviceProfile = getSelectedProfileId;
export const clearDeviceProfile = clearSelectedProfile;

// Track IDs response (lightweight for shuffle-all)
export interface TrackIdsResponse {
  ids: string[];
  total: number;
}

export const tracksApi = {
  list: async (params?: {
    page?: number;
    page_size?: number;
    search?: string;
    artist?: string;
    album?: string;
    genre?: string;
    year_from?: number;
    year_to?: number;
    energy_min?: number;
    energy_max?: number;
    valence_min?: number;
    valence_max?: number;
    include_features?: boolean;
    sort_by?: string;
    sort_order?: 'asc' | 'desc';
  }): Promise<TrackListResponse> => {
    const { data } = await api.get('/tracks', { params });
    return data;
  },

  /**
   * Get all track IDs matching filters (lightweight for shuffle-all).
   * Use shuffle=true to get randomized order.
   * Use start_with to ensure a specific track appears first.
   */
  getIds: async (params?: {
    shuffle?: boolean;
    start_with?: string;
    search?: string;
    artist?: string;
    album?: string;
    genre?: string;
    year_from?: number;
    year_to?: number;
    energy_min?: number;
    energy_max?: number;
    valence_min?: number;
    valence_max?: number;
    sort_by?: string;
    sort_order?: 'asc' | 'desc';
  }): Promise<TrackIdsResponse> => {
    const { data } = await api.get('/tracks/ids', { params });
    return data;
  },

  /**
   * Get full track metadata for a batch of IDs.
   * Preserves order of requested IDs. Limited to 50 tracks.
   */
  getBatch: async (ids: string[]): Promise<Track[]> => {
    const { data } = await api.post('/tracks/batch', { ids });
    return data;
  },

  get: async (id: string): Promise<Track> => {
    const { data } = await api.get(`/tracks/${id}`);
    return data;
  },

  getSimilar: async (id: string, limit = 10): Promise<Track[]> => {
    const { data } = await api.get(`/tracks/${id}/similar`, {
      params: { limit },
    });
    return data;
  },

  getStreamUrl: (id: string): string => {
    return `/api/v1/tracks/${id}/stream`;
  },

  getArtworkUrl: (id: string, size: 'full' | 'thumb' = 'full'): string => {
    return `/api/v1/tracks/${id}/artwork?size=${size}`;
  },

  getLyrics: async (id: string): Promise<LyricsResponse> => {
    const { data } = await api.get(`/tracks/${id}/lyrics`);
    return data;
  },

  /**
   * Get the 0-based index of a track in the sorted/filtered list.
   * Used for auto-scrolling to the current track after navigation.
   */
  getIndex: async (
    id: string,
    filters?: {
      search?: string;
      artist?: string;
      album?: string;
    }
  ): Promise<{ index: number }> => {
    const { data } = await api.get(`/tracks/${id}/index`, { params: filters });
    return data;
  },

  enrich: async (id: string): Promise<{ status: string; message: string }> => {
    const { data } = await api.post(`/tracks/${id}/enrich`);
    return data;
  },

  // Metadata editing
  getMetadata: async (id: string): Promise<TrackMetadataResponse> => {
    const { data } = await api.get(`/tracks/${id}/metadata`);
    return data;
  },

  updateMetadata: async (
    id: string,
    update: TrackMetadataUpdate
  ): Promise<TrackMetadataResponse> => {
    const { data } = await api.patch(`/tracks/${id}/metadata`, update);
    return data;
  },

  // Artwork
  deleteArtwork: async (id: string): Promise<{ success: boolean; message: string }> => {
    const { data } = await api.delete(`/tracks/${id}/artwork`);
    return data;
  },

  // Discovery
  getDiscover: async (
    id: string,
    trackLimit = 6,
    artistLimit = 6
  ): Promise<TrackDiscoverResponse> => {
    const { data } = await api.get(`/tracks/${id}/discover`, {
      params: { track_limit: trackLimit, artist_limit: artistLimit },
    });
    return data;
  },

  // Audio fingerprint identification
  identify: async (
    id: string,
    params?: { min_score?: number; limit?: number }
  ): Promise<IdentifyTrackResponse> => {
    const { data } = await api.post(`/tracks/${id}/identify`, null, {
      params,
    });
    return data;
  },
};

// Audio fingerprint identification types
export interface IdentifyCandidate {
  acoustid_score: number;
  musicbrainz_recording_id: string;
  title: string | null;
  artist: string | null;
  album: string | null;
  album_artist: string | null;
  year: number | null;
  track_number: number | null;
  disc_number: number | null;
  genre: string | null;
  composer: string | null;
  artwork_url: string | null;
  features: Record<string, number | string | null>;
  musicbrainz_url: string;
}

export interface IdentifyTrackResponse {
  track_id: string;
  fingerprint_generated: boolean;
  error: string | null;
  error_type: string | null;
  candidates: IdentifyCandidate[];
}

// Bulk identification types
export interface BulkIdentifyTaskResponse {
  task_id: string;
  status: string;
  message: string;
}

export interface BulkIdentifyProgress {
  task_id: string;
  status: 'running' | 'completed' | 'error';
  phase: string;
  total_tracks: number;
  processed_tracks: number;
  current_track: string | null;
  results: IdentifyTrackResponse[];
  errors: string[];
  started_at: string | null;
}

export const bulkTracksApi = {
  startIdentify: async (trackIds: string[]): Promise<BulkIdentifyTaskResponse> => {
    const { data } = await api.post('/tracks/bulk/identify', {
      track_ids: trackIds,
    });
    return data;
  },

  getIdentifyProgress: async (taskId: string): Promise<BulkIdentifyProgress> => {
    const { data } = await api.get(`/tracks/bulk/identify/${taskId}`);
    return data;
  },
};

// Track metadata types
export interface TrackMetadataUpdate {
  // Core metadata
  title?: string | null;
  artist?: string | null;
  album?: string | null;
  album_artist?: string | null;
  track_number?: number | null;
  disc_number?: number | null;
  year?: number | null;
  genre?: string | null;

  // Extended metadata
  composer?: string | null;
  conductor?: string | null;
  lyricist?: string | null;
  grouping?: string | null;
  comment?: string | null;

  // Sort fields
  sort_artist?: string | null;
  sort_album?: string | null;
  sort_title?: string | null;

  // Lyrics
  lyrics?: string | null;

  // User overrides for analysis values
  user_overrides?: Record<string, number | string | null>;

  // Whether to write changes to the audio file
  write_to_file?: boolean;
}

export interface TrackMetadataResponse {
  id: string;
  file_path: string;

  // Core metadata
  title: string | null;
  artist: string | null;
  album: string | null;
  album_artist: string | null;
  track_number: number | null;
  disc_number: number | null;
  year: number | null;
  genre: string | null;

  // Extended metadata
  composer: string | null;
  conductor: string | null;
  lyricist: string | null;
  grouping: string | null;
  comment: string | null;

  // Sort fields
  sort_artist: string | null;
  sort_album: string | null;
  sort_title: string | null;

  // Lyrics
  lyrics: string | null;

  // User overrides
  user_overrides: Record<string, number | string | null>;

  // Audio info
  duration_seconds: number | null;
  format: string | null;

  // Analysis features (with user overrides applied)
  features: {
    bpm: number | null;
    key: string | null;
    energy: number | null;
    danceability: number | null;
    valence: number | null;
    acousticness: number | null;
    instrumentalness: number | null;
    speechiness: number | null;
  } | null;

  // Write status (only present after update)
  file_write_status?: string | null;
  file_write_error?: string | null;
}

export interface LyricLine {
  time: number;
  text: string;
}

export interface LyricsResponse {
  synced: boolean;
  lines: LyricLine[];
  plain_text: string;
  source: string;
}

export interface TrackDiscoverSimilarArtist {
  name: string;
  match_score: number;
  in_library: boolean;
  track_count: number | null;
  image_url: string | null;
  lastfm_url: string | null;
  bandcamp_url: string | null;
}

export interface TrackDiscoverResponse {
  track_id: string;
  artist: string | null;
  title: string | null;
  similar_tracks: Track[];
  similar_artists: TrackDiscoverSimilarArtist[];
  bandcamp_artist_url: string | null;
  bandcamp_track_url: string | null;
}

export interface SpotifyStatus {
  configured: boolean;
  connected: boolean;
  spotify_user_id: string | null;
  last_sync: string | null;
  stats: {
    total_favorites: number;
    matched: number;
    unmatched: number;
    match_rate: number;
  } | null;
}

export interface SpotifySyncResponse {
  status: string;
  message: string;
  stats?: {
    fetched: number;
    new: number;
    matched: number;
    unmatched: number;
  };
  progress?: SpotifySyncProgress | null;
}

export interface SpotifySyncProgress {
  phase: string;
  tracks_fetched: number;
  tracks_processed: number;
  tracks_total: number;
  new_favorites: number;
  matched: number;
  unmatched: number;
  current_track: string | null;
  started_at: string | null;
  errors: string[];
}

export interface StoreSearchLink {
  name: string;
  url: string;
}

export interface UnmatchedTrack {
  spotify_id: string;
  name: string | null;
  artist: string | null;
  album: string | null;
  added_at: string | null;
  popularity: number | null;
  search_links: Record<string, StoreSearchLink>;
}

export const spotifyApi = {
  getStatus: async (): Promise<SpotifyStatus> => {
    const { data } = await api.get('/spotify/status');
    return data;
  },

  getAuthUrl: async (): Promise<{ auth_url: string; state: string }> => {
    const { data } = await api.get('/spotify/auth');
    return data;
  },

  sync: async (includeTopTracks = true, favoriteMatched = false): Promise<SpotifySyncResponse> => {
    const { data } = await api.post('/spotify/sync', null, {
      params: { include_top_tracks: includeTopTracks, favorite_matched: favoriteMatched },
      timeout: 300000, // 5 minute timeout for large libraries
    });
    return data;
  },

  disconnect: async (): Promise<{ status: string }> => {
    const { data } = await api.post('/spotify/disconnect');
    return data;
  },

  getSyncStatus: async (): Promise<SpotifySyncResponse> => {
    const { data } = await api.get('/spotify/sync/status');
    return data;
  },

  getUnmatched: async (params?: {
    limit?: number;
    sort_by?: 'popularity' | 'added_at';
  }): Promise<UnmatchedTrack[]> => {
    const { data } = await api.get('/spotify/unmatched', { params });
    return data;
  },
};

export interface VideoSearchResult {
  video_id: string;
  title: string;
  channel: string;
  duration: number;
  thumbnail_url: string;
  url: string;
}

export interface VideoStatus {
  has_video: boolean;
  download_status: string | null;
  progress: number | null;
  error: string | null;
}

export const videosApi = {
  search: async (trackId: string, limit = 5): Promise<VideoSearchResult[]> => {
    const { data } = await api.get(`/videos/${trackId}/search`, {
      params: { limit },
    });
    return data;
  },

  getStatus: async (trackId: string): Promise<VideoStatus> => {
    const { data } = await api.get(`/videos/${trackId}/status`);
    return data;
  },

  download: async (trackId: string, videoUrl: string): Promise<{ status: string; message: string }> => {
    const { data } = await api.post(`/videos/${trackId}/download`, {
      video_url: videoUrl,
    });
    return data;
  },

  getStreamUrl: (trackId: string): string => {
    return `/api/v1/videos/${trackId}/stream`;
  },

  delete: async (trackId: string): Promise<{ status: string }> => {
    const { data } = await api.delete(`/videos/${trackId}`);
    return data;
  },
};

export interface LastfmStatus {
  configured: boolean;
  connected: boolean;
  username: string | null;
}

export const lastfmApi = {
  getStatus: async (): Promise<LastfmStatus> => {
    const { data } = await api.get('/lastfm/status');
    return data;
  },

  getAuthUrl: async (): Promise<{ auth_url: string }> => {
    const { data } = await api.get('/lastfm/auth');
    return data;
  },

  callback: async (token: string): Promise<{ status: string; username: string }> => {
    const { data } = await api.post('/lastfm/callback', null, {
      params: { token },
    });
    return data;
  },

  disconnect: async (): Promise<{ status: string }> => {
    const { data } = await api.post('/lastfm/disconnect');
    return data;
  },

  updateNowPlaying: async (trackId: string): Promise<{ status: string; message: string }> => {
    const { data } = await api.post('/lastfm/now-playing', { track_id: trackId });
    return data;
  },

  scrobble: async (trackId: string, timestamp?: number): Promise<{ status: string; message: string }> => {
    const { data } = await api.post('/lastfm/scrobble', {
      track_id: trackId,
      timestamp,
    });
    return data;
  },
};

export interface ClapStatus {
  enabled: boolean;
  reason: string;
  ram_gb: number | null;
  ram_sufficient: boolean;
  env_override: boolean;
  explicit_setting: boolean | null;
}

export interface AppSettingsResponse {
  spotify_client_id: string | null;
  spotify_client_secret: string | null;
  lastfm_api_key: string | null;
  lastfm_api_secret: string | null;
  anthropic_api_key: string | null;
  spotify_configured: boolean;
  lastfm_configured: boolean;
  // Metadata enrichment
  auto_enrich_metadata: boolean;
  enrich_overwrite_existing: boolean;
  // Analysis settings
  clap_embeddings_enabled: boolean | null;
  clap_status: ClapStatus;
  // Playlist generation
  playlist_discovery_mode: string;
}

export interface AppSettingsUpdate {
  spotify_client_id?: string;
  spotify_client_secret?: string;
  lastfm_api_key?: string;
  lastfm_api_secret?: string;
  anthropic_api_key?: string;
  // Metadata enrichment
  auto_enrich_metadata?: boolean;
  enrich_overwrite_existing?: boolean;
  // Analysis settings
  clap_embeddings_enabled?: boolean | null;
  // Playlist generation
  playlist_discovery_mode?: string;
}

export const appSettingsApi = {
  get: async (): Promise<AppSettingsResponse> => {
    const { data } = await api.get('/settings');
    return data;
  },

  update: async (settings: AppSettingsUpdate): Promise<AppSettingsResponse> => {
    const { data } = await api.put('/settings', settings);
    return data;
  },

  clearSpotify: async (): Promise<{ status: string }> => {
    const { data } = await api.delete('/settings/spotify');
    return data;
  },

  clearLastfm: async (): Promise<{ status: string }> => {
    const { data } = await api.delete('/settings/lastfm');
    return data;
  },
};

export interface ImportResult {
  status: string;
  message: string;
  import_path: string | null;
  files_found: number;
  files: string[];
}

export interface RecentImport {
  name: string;
  path: string;
  file_count: number;
  created_at: string | null;
}

// Unified Sync Types
export type SyncPhase = 'idle' | 'discovering' | 'reading' | 'features' | 'embeddings' | 'complete' | 'error';

export interface SyncProgress {
  phase: SyncPhase;
  phase_message: string;

  // Discovery/scan metrics
  files_discovered: number;
  files_processed: number;
  files_total: number;
  new_tracks: number;
  updated_tracks: number;
  unchanged_tracks: number;
  relocated_tracks: number;
  marked_missing: number;
  recovered: number;

  // Analysis metrics
  tracks_analyzed: number;
  tracks_pending_analysis: number;
  tracks_total: number;
  analysis_percent: number;

  // Overall
  started_at: string | null;
  current_item: string | null;
  last_heartbeat: string | null;
  errors: string[];
}

export interface SyncStatus {
  status: 'idle' | 'running' | 'completed' | 'error' | 'already_running';
  message: string;
  progress: SyncProgress | null;
}

// Library Browser Types
export interface ArtistSummary {
  name: string;
  track_count: number;
  album_count: number;
  first_track_id: string;
}

export interface ArtistListResponse {
  items: ArtistSummary[];
  total: number;
  page: number;
  page_size: number;
}

// Artist Detail
export interface ArtistAlbum {
  name: string;
  year: number | null;
  track_count: number;
  first_track_id: string;
}

export interface ArtistTrack {
  id: string;
  title: string | null;
  album: string | null;
  track_number: number | null;
  duration_seconds: number | null;
  year: number | null;
}

export interface ArtistDetailResponse {
  name: string;
  track_count: number;
  album_count: number;
  total_duration_seconds: number;

  // From Last.fm
  bio_summary: string | null;
  bio_content: string | null;
  image_url: string | null;
  lastfm_url: string | null;
  listeners: number | null;
  playcount: number | null;
  tags: string[];
  similar_artists: Array<{
    name: string;
    match_score: number;
    in_library: boolean;
    track_count: number | null;
    image_url: string | null;
    lastfm_url: string | null;
    bandcamp_url: string | null;
  }>;

  // Library content
  albums: ArtistAlbum[];
  tracks: ArtistTrack[];
  first_track_id: string;

  // Cache status
  lastfm_fetched: boolean;
  lastfm_error: string | null;
}

export interface AlbumSummary {
  name: string;
  artist: string;
  year: number | null;
  track_count: number;
  first_track_id: string;
}

export interface AlbumListResponse {
  items: AlbumSummary[];
  total: number;
  page: number;
  page_size: number;
}

export interface AlbumTrack {
  id: string;
  title: string | null;
  track_number: number | null;
  disc_number: number | null;
  duration_seconds: number | null;
}

export interface SimilarAlbumInfo {
  name: string;
  artist: string;
  year: number | null;
  track_count: number;
  first_track_id: string;
  similarity_score: number;
}

export interface DiscoverAlbumInfo {
  name: string;
  artist: string;
  image_url: string | null;
  lastfm_url: string | null;
  bandcamp_url: string | null;
}

export interface AlbumDetailResponse {
  name: string;
  artist: string;
  album_artist: string | null;
  year: number | null;
  genre: string | null;
  track_count: number;
  total_duration_seconds: number;
  first_track_id: string;
  tracks: AlbumTrack[];
  similar_albums: SimilarAlbumInfo[];
  discover_albums: DiscoverAlbumInfo[];
  other_albums_by_artist: SimilarAlbumInfo[];
}

// Year Distribution (for Timeline browser)
export interface YearCount {
  year: number;
  track_count: number;
  album_count: number;
  artist_count: number;
}

export interface YearDistributionResponse {
  years: YearCount[];
  total_with_year: number;
  total_without_year: number;
  min_year: number | null;
  max_year: number | null;
}

// Mood Distribution (for MoodGrid browser)
export interface MoodCell {
  energy_min: number;
  energy_max: number;
  valence_min: number;
  valence_max: number;
  track_count: number;
  sample_track_ids: string[];
}

export interface MoodDistributionResponse {
  cells: MoodCell[];
  grid_size: number;
  total_with_mood: number;
  total_without_mood: number;
}

// Music Map (for MusicMap browser)
export interface MapNode {
  id: string;
  name: string;
  x: number;
  y: number;
  track_count: number;
  first_track_id: string;
}

export interface MapEdge {
  source: string;
  target: string;
  weight: number;
}

export interface MusicMapResponse {
  nodes: MapNode[];
  edges: MapEdge[];
  entity_type: string;
  total_entities: number;
}

// Ego-centric Music Map
export interface EgoMapCenter {
  name: string;
  track_count: number;
  first_track_id: string;
}

export interface EgoMapArtist {
  name: string;
  x: number;
  y: number;
  distance: number;
  track_count: number;
  first_track_id: string;
}

export interface EgoMapResponse {
  center: EgoMapCenter;
  artists: EgoMapArtist[];
  mode: string;
  total_artists: number;
}

// 3D Music Map
export interface MapNode3D {
  id: string;
  name: string;
  x: number;
  y: number;
  z: number;
  track_count: number;
  first_track_id: string;
  representative_track_id?: string; // Track closest to artist's audio centroid
}

export interface MusicMap3DResponse {
  nodes: MapNode3D[];
  entity_type: string;
  total_entities: number;
}

// Letter Index (for Alphabet Bar navigation)
export interface LetterIndexResponse {
  letters: Record<string, number>;  // {"A": 0, "B": 47, "C": 123, "#": 500}
  total: number;
}

export const libraryApi = {
  getStats: async (): Promise<LibraryStats> => {
    const { data } = await api.get('/library/stats');
    return data;
  },

  listArtists: async (params?: {
    search?: string;
    sort_by?: 'name' | 'track_count' | 'album_count';
    page?: number;
    page_size?: number;
    has_embeddings?: boolean;
  }): Promise<ArtistListResponse> => {
    const { data } = await api.get('/library/artists', { params });
    return data;
  },

  getArtist: async (
    artistName: string,
    refreshLastfm = false
  ): Promise<ArtistDetailResponse> => {
    const { data } = await api.get(
      `/library/artists/${encodeURIComponent(artistName)}`,
      { params: { refresh_lastfm: refreshLastfm } }
    );
    return data;
  },

  listAlbums: async (params?: {
    artist?: string;
    search?: string;
    sort_by?: 'name' | 'year' | 'track_count' | 'artist';
    page?: number;
    page_size?: number;
  }): Promise<AlbumListResponse> => {
    const { data } = await api.get('/library/albums', { params });
    return data;
  },

  getAlbum: async (
    artistName: string,
    albumName: string,
    similarLimit = 8
  ): Promise<AlbumDetailResponse> => {
    const { data } = await api.get(
      `/library/albums/${encodeURIComponent(artistName)}/${encodeURIComponent(albumName)}`,
      { params: { similar_limit: similarLimit } }
    );
    return data;
  },

  getYearDistribution: async (): Promise<YearDistributionResponse> => {
    const { data } = await api.get('/library/years');
    return data;
  },

  getMoodDistribution: async (gridSize = 10): Promise<MoodDistributionResponse> => {
    const { data } = await api.get('/library/mood-distribution', {
      params: { grid_size: gridSize },
    });
    return data;
  },

  getMusicMap: async (params?: {
    entity_type?: 'artists' | 'albums';
    limit?: number;
  }): Promise<MusicMapResponse> => {
    const { data } = await api.get('/library/map', { params });
    return data;
  },

  getEgoMap: async (params: {
    center: string;
    limit?: number;
    mode?: 'radial';
  }): Promise<EgoMapResponse> => {
    const { data } = await api.get('/library/map/ego', {
      params: {
        center: params.center,
        limit: params.limit ?? 200,
        mode: params.mode ?? 'radial',
      },
    });
    return data;
  },

  get3DMap: async (params?: {
    entity_type?: 'artists' | 'albums';
  }): Promise<MusicMap3DResponse> => {
    const { data } = await api.get('/library/map/3d', {
      params: {
        entity_type: params?.entity_type ?? 'artists',
      },
    });
    return data;
  },

  sync: async (options: {
    rereadUnchanged?: boolean;
  } = {}): Promise<SyncStatus> => {
    const { data } = await api.post('/library/sync', null, {
      params: {
        reread_unchanged: options.rereadUnchanged ?? false,
      },
    });
    return data;
  },

  getSyncStatus: async (): Promise<SyncStatus> => {
    const { data } = await api.get('/library/sync/status');
    return data;
  },

  cancelSync: async (): Promise<{ status: string; message: string }> => {
    const { data } = await api.post('/library/sync/cancel');
    return data;
  },

  importMusic: async (
    file: File,
    onProgress?: (progress: number) => void
  ): Promise<ImportResult> => {
    const formData = new FormData();
    formData.append('file', file);
    const { data } = await api.post('/library/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (progressEvent) => {
        if (progressEvent.total && onProgress) {
          const percentCompleted = Math.round(
            (progressEvent.loaded * 100) / progressEvent.total
          );
          onProgress(percentCompleted);
        }
      },
    });
    return data;
  },

  getRecentImports: async (limit = 10): Promise<RecentImport[]> => {
    const { data } = await api.get('/library/imports/recent', {
      params: { limit },
    });
    return data;
  },

  getArtistImageUrl: (
    artistName: string,
    size: 'small' | 'medium' | 'large' | 'extralarge' = 'large'
  ): string => {
    // Cache version param to bust browser cache when image sources change
    const cacheVersion = 'v2';
    return `/api/v1/library/artists/${encodeURIComponent(artistName)}/image?size=${size}&_cv=${cacheVersion}`;
  },

  getLetterIndex: async (params: {
    entity_type: 'tracks' | 'artists' | 'albums';
    sort_field: string;
    search?: string;
    artist?: string;
    album?: string;
  }): Promise<LetterIndexResponse> => {
    const { data } = await api.get('/library/letter-index', { params });
    return data;
  },

  getDiscover: async (params?: {
    releases_limit?: number;
    recommendations_limit?: number;
    favorites_limit?: number;
  }): Promise<LibraryDiscoverResponse> => {
    const { data } = await api.get('/library/discover', { params });
    return data;
  },
};

// Library Discover types
export interface DiscoverNewRelease {
  id: string;
  artist: string;
  album: string;
  release_date: string | null;
  source: string;
  image_url: string | null;
  bandcamp_url: string | null;
  owned_locally: boolean;
}

export interface DiscoverRecommendedArtist {
  name: string;
  match_score: number;
  in_library: boolean;
  track_count: number | null;
  image_url: string | null;
  lastfm_url: string | null;
  bandcamp_url: string | null;
  based_on_artist: string;
}

export interface DiscoverUnmatchedFavorite {
  spotify_track_id: string;
  name: string;
  artist: string;
  album: string | null;
  image_url: string | null;
  bandcamp_url: string | null;
}

export interface LibraryDiscoverResponse {
  new_releases: DiscoverNewRelease[];
  new_releases_total: number;
  recommended_artists: DiscoverRecommendedArtist[];
  unmatched_favorites: DiscoverUnmatchedFavorite[];
  unmatched_total: number;
  recently_added_count: number;
}

// Smart Playlists
export interface SmartPlaylistRule {
  field: string;
  operator: string;
  value?: unknown;
}

export interface SmartPlaylist {
  id: string;
  name: string;
  description: string | null;
  rules: SmartPlaylistRule[];
  match_mode: 'all' | 'any';
  order_by: string;
  order_direction: 'asc' | 'desc';
  max_tracks: number | null;
  cached_track_count: number;
  last_refreshed_at: string | null;
  auto_download: boolean;
  created_at: string;
  updated_at: string;
}

export interface SmartPlaylistCreate {
  name: string;
  description?: string;
  rules: SmartPlaylistRule[];
  match_mode?: 'all' | 'any';
  order_by?: string;
  order_direction?: 'asc' | 'desc';
  max_tracks?: number;
}

export interface SmartPlaylistTracksResponse {
  playlist: SmartPlaylist;
  tracks: Array<{
    id: string;
    title: string | null;
    artist: string | null;
    album: string | null;
    duration_seconds: number | null;
    genre: string | null;
    year: number | null;
  }>;
  total: number;
}

export interface AvailableFields {
  track_fields: Array<{
    name: string;
    type: string;
    description: string;
  }>;
  analysis_fields: Array<{
    name: string;
    type: string;
    description: string;
    range?: [number, number];
  }>;
  play_history_fields?: Array<{
    name: string;
    type: string;
    description: string;
  }>;
  operators: {
    string: string[];
    number: string[];
    date: string[];
    boolean?: string[];
    list: string[];
  };
}

export interface PlaylistImportResult {
  playlist_id: string;
  playlist_name: string;
  total_tracks: number;
  matched_tracks: number;
  unmatched_tracks: number;
  tracks: Array<{
    title: string;
    artist: string;
    matched: boolean;
    matched_track_id: string | null;
    confidence: number;
  }>;
}

export const playlistSharingApi = {
  importPlaylist: async (file: File): Promise<PlaylistImportResult> => {
    const formData = new FormData();
    formData.append('file', file);
    const { data } = await api.post('/playlists/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return data;
  },
};

export const smartPlaylistsApi = {
  list: async (): Promise<SmartPlaylist[]> => {
    const { data } = await api.get('/smart-playlists');
    return data;
  },

  get: async (id: string): Promise<SmartPlaylist> => {
    const { data } = await api.get(`/smart-playlists/${id}`);
    return data;
  },

  create: async (playlist: SmartPlaylistCreate): Promise<SmartPlaylist> => {
    const { data } = await api.post('/smart-playlists', playlist);
    return data;
  },

  update: async (id: string, playlist: Partial<SmartPlaylistCreate> & { auto_download?: boolean }): Promise<SmartPlaylist> => {
    const { data } = await api.put(`/smart-playlists/${id}`, playlist);
    return data;
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/smart-playlists/${id}`);
  },

  getTracks: async (id: string, limit = 100, offset = 0): Promise<SmartPlaylistTracksResponse> => {
    const { data } = await api.get(`/smart-playlists/${id}/tracks`, {
      params: { limit, offset },
    });
    return data;
  },

  refresh: async (id: string): Promise<SmartPlaylist> => {
    const { data } = await api.post(`/smart-playlists/${id}/refresh`);
    return data;
  },

  getAvailableFields: async (): Promise<AvailableFields> => {
    const { data } = await api.get('/smart-playlists/fields/available');
    return data;
  },
};

// Playlists API (static playlists with track IDs)
export interface Playlist {
  id: string;
  name: string;
  description: string | null;
  is_auto_generated: boolean;
  is_wishlist: boolean;
  generation_prompt: string | null;
  track_count: number;
  local_track_count: number;
  external_track_count: number;
  auto_download: boolean;
  created_at: string;
  updated_at: string;
}

export interface PlaylistTrack {
  id: string; // track_id or external_track_id
  playlist_track_id: string; // PlaylistTrack.id for reordering/removal
  type: 'local' | 'external';
  title: string | null;
  artist: string | null;
  album: string | null;
  duration_seconds: number | null;
  position: number;

  // External track fields (only present when type === 'external')
  is_matched?: boolean;
  matched_track_id?: string | null;
  match_confidence?: number | null;
  preview_url?: string | null;
  external_links?: Record<string, string>;
}

export interface PlaylistDetail {
  id: string;
  name: string;
  description: string | null;
  is_auto_generated: boolean;
  is_wishlist: boolean;
  generation_prompt: string | null;
  tracks: PlaylistTrack[];
  auto_download: boolean;
  created_at: string;
  updated_at: string;
}

export interface PlaylistCreate {
  name: string;
  description?: string;
  track_ids: string[];
  is_auto_generated?: boolean;
  generation_prompt?: string;
}

export interface RecommendedArtist {
  name: string;
  source: string;
  match_score: number;
  image_url: string | null;
  external_url: string | null;
  local_track_count: number;
}

export interface RecommendedTrack {
  title: string;
  artist: string;
  source: string;
  match_score: number;
  external_url: string | null;
  local_track_id: string | null;
  album: string | null;
}

export interface PlaylistRecommendations {
  artists: RecommendedArtist[];
  tracks: RecommendedTrack[];
  sources_used: string[];
}

export const playlistsApi = {
  list: async (includeAuto = true): Promise<Playlist[]> => {
    const { data } = await api.get('/playlists', {
      params: { include_auto: includeAuto },
    });
    return data;
  },

  get: async (id: string): Promise<PlaylistDetail> => {
    const { data } = await api.get(`/playlists/${id}`);
    return data;
  },

  create: async (playlist: PlaylistCreate): Promise<PlaylistDetail> => {
    const { data } = await api.post('/playlists', playlist);
    return data;
  },

  update: async (id: string, playlist: { name?: string; description?: string; auto_download?: boolean }): Promise<Playlist> => {
    const { data } = await api.put(`/playlists/${id}`, playlist);
    return data;
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/playlists/${id}`);
  },

  addTracks: async (id: string, trackIds: string[]): Promise<PlaylistDetail> => {
    const { data } = await api.post(`/playlists/${id}/tracks`, trackIds);
    return data;
  },

  removeTrack: async (id: string, trackId: string): Promise<void> => {
    await api.delete(`/playlists/${id}/tracks/${trackId}`);
  },

  reorderTracks: async (id: string, trackIds: string[]): Promise<PlaylistDetail> => {
    const { data } = await api.put(`/playlists/${id}/tracks/reorder`, { track_ids: trackIds });
    return data;
  },

  getRecommendations: async (
    id: string,
    params?: { artist_limit?: number; track_limit?: number }
  ): Promise<PlaylistRecommendations> => {
    const { data } = await api.get(`/playlists/${id}/recommendations`, { params });
    return data;
  },

  removeItem: async (playlistId: string, playlistTrackId: string): Promise<void> => {
    await api.delete(`/playlists/${playlistId}/items/${playlistTrackId}`);
  },

  reorderItems: async (id: string, playlistTrackIds: string[]): Promise<PlaylistDetail> => {
    const { data } = await api.put(`/playlists/${id}/tracks/reorder`, {
      playlist_track_ids: playlistTrackIds,
    });
    return data;
  },

  // Wishlist
  getWishlist: async (): Promise<PlaylistDetail> => {
    const { data } = await api.get('/playlists/wishlist');
    return data;
  },

  addToWishlist: async (request: {
    title: string;
    artist: string;
    album?: string;
    spotify_id?: string;
    preview_url?: string;
    external_data?: Record<string, unknown>;
  }): Promise<PlaylistDetail> => {
    const { data } = await api.post('/playlists/wishlist/add', request);
    return data;
  },
};

// External Tracks API
export interface ExternalTrack {
  id: string;
  title: string;
  artist: string;
  album: string | null;
  duration_seconds: number | null;
  track_number: number | null;
  year: number | null;
  source: string;
  preview_url: string | null;
  preview_source: string | null;
  external_data: Record<string, unknown>;
  is_matched: boolean;
  matched_track_id: string | null;
  matched_at: string | null;
  match_confidence: number | null;
  match_method: string | null;
  spotify_id: string | null;
  isrc: string | null;
  created_at: string;
}

export interface ExternalTrackStats {
  total: number;
  matched: number;
  unmatched: number;
  match_rate: number;
  by_source: Record<string, number>;
}

export const externalTracksApi = {
  list: async (params?: {
    matched?: boolean;
    source?: string;
    limit?: number;
    offset?: number;
  }): Promise<ExternalTrack[]> => {
    const { data } = await api.get('/external-tracks', { params });
    return data;
  },

  getStats: async (): Promise<ExternalTrackStats> => {
    const { data } = await api.get('/external-tracks/stats');
    return data;
  },

  get: async (id: string): Promise<ExternalTrack> => {
    const { data } = await api.get(`/external-tracks/${id}`);
    return data;
  },

  create: async (track: {
    title: string;
    artist: string;
    album?: string;
    isrc?: string;
    spotify_id?: string;
    preview_url?: string;
  }): Promise<ExternalTrack> => {
    const { data } = await api.post('/external-tracks', track);
    return data;
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/external-tracks/${id}`);
  },

  manualMatch: async (externalTrackId: string, trackId: string): Promise<ExternalTrack> => {
    const { data } = await api.post(`/external-tracks/${externalTrackId}/match`, {
      track_id: trackId,
    });
    return data;
  },

  removeMatch: async (externalTrackId: string): Promise<ExternalTrack> => {
    const { data } = await api.delete(`/external-tracks/${externalTrackId}/match`);
    return data;
  },

  rematchAll: async (runInBackground = false): Promise<{
    processed: number;
    matched: number;
    task_id?: string;
  }> => {
    const { data } = await api.post('/external-tracks/rematch', null, {
      params: { run_in_background: runInBackground },
    });
    return data;
  },
};

// Spotify Playlist Import API
export interface SpotifyPlaylistInfo {
  id: string;
  name: string;
  description: string | null;
  track_count: number;
  image_url: string | null;
  external_url: string | null;
  owner: string | null;
  public: boolean | null;
}

export interface SpotifyPlaylistTrack {
  spotify_id: string;
  title: string;
  artist: string | null;
  album: string | null;
  duration_ms: number | null;
  preview_url: string | null;
  in_library: boolean;
  local_track_id: string | null;
}

export interface SpotifyPlaylistTracksResponse {
  playlist_name: string;
  playlist_description: string | null;
  tracks: SpotifyPlaylistTrack[];
  total: number;
  in_library: number;
  missing: number;
  match_rate: string;
}

export interface ImportedPlaylist {
  id: string;
  name: string;
  description: string | null;
  track_count: number;
}

export const spotifyPlaylistsApi = {
  list: async (limit = 50): Promise<SpotifyPlaylistInfo[]> => {
    const { data } = await api.get('/spotify/playlists', { params: { limit } });
    return data;
  },

  getTracks: async (
    playlistId: string,
    limit = 100
  ): Promise<SpotifyPlaylistTracksResponse> => {
    const { data } = await api.get(`/spotify/playlists/${playlistId}/tracks`, {
      params: { limit },
    });
    return data;
  },

  import: async (
    playlistId: string,
    options?: {
      name?: string;
      description?: string;
      include_missing?: boolean;
    }
  ): Promise<ImportedPlaylist> => {
    const { data } = await api.post(`/spotify/playlists/${playlistId}/import`, options);
    return data;
  },
};

// Profile API
export interface ProfileResponse {
  id: string;
  name: string;
  color: string | null;
  avatar_url: string | null;
  created_at: string;
  has_spotify: boolean;
  has_lastfm: boolean;
}

export interface ProfileCreate {
  name: string;
  color?: string;
}

export const profilesApi = {
  list: async (): Promise<ProfileResponse[]> => {
    const { data } = await api.get('/profiles');
    return data;
  },

  create: async (profile: ProfileCreate): Promise<ProfileResponse> => {
    const { data } = await api.post('/profiles', profile);
    return data;
  },

  get: async (id: string): Promise<ProfileResponse> => {
    const { data } = await api.get(`/profiles/${id}`);
    return data;
  },

  getMe: async (): Promise<ProfileResponse> => {
    const { data } = await api.get('/profiles/me');
    return data;
  },

  update: async (id: string, profile: Partial<ProfileCreate>): Promise<ProfileResponse> => {
    const { data } = await api.put(`/profiles/${id}`, profile);
    return data;
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/profiles/${id}`);
  },

  uploadAvatar: async (id: string, file: File): Promise<ProfileResponse> => {
    const formData = new FormData();
    formData.append('file', file);
    const { data } = await api.post(`/profiles/${id}/avatar`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return data;
  },

  deleteAvatar: async (id: string): Promise<ProfileResponse> => {
    const { data } = await api.delete(`/profiles/${id}/avatar`);
    return data;
  },

  getAvatarUrl: (id: string): string => {
    return `/api/v1/profiles/${id}/avatar`;
  },
};

// Favorites API
export interface FavoriteTrack {
  id: string;
  title: string | null;
  artist: string | null;
  album: string | null;
  duration_seconds: number | null;
  genre: string | null;
  year: number | null;
  favorited_at: string;
}

export interface FavoritesListResponse {
  favorites: FavoriteTrack[];
  total: number;
}

export interface FavoriteStatusResponse {
  track_id: string;
  is_favorite: boolean;
}

export const favoritesApi = {
  list: async (limit = 100, offset = 0): Promise<FavoritesListResponse> => {
    const { data } = await api.get('/favorites', { params: { limit, offset } });
    return data;
  },

  add: async (trackId: string): Promise<FavoriteStatusResponse> => {
    const { data } = await api.post(`/favorites/${trackId}`);
    return data;
  },

  remove: async (trackId: string): Promise<FavoriteStatusResponse> => {
    const { data } = await api.delete(`/favorites/${trackId}`);
    return data;
  },

  check: async (trackId: string): Promise<FavoriteStatusResponse> => {
    const { data } = await api.get(`/favorites/${trackId}`);
    return data;
  },

  toggle: async (trackId: string): Promise<FavoriteStatusResponse> => {
    const { data } = await api.post(`/favorites/${trackId}/toggle`);
    return data;
  },

  getAutoDownload: async (): Promise<{ enabled: boolean }> => {
    const { data } = await api.get('/favorites/auto-download');
    return data;
  },

  setAutoDownload: async (enabled: boolean): Promise<{ enabled: boolean }> => {
    const { data } = await api.put('/favorites/auto-download', { enabled });
    return data;
  },
};

// Play Tracking API
export interface PlayRecordResponse {
  track_id: string;
  play_count: number;
  total_play_seconds: number;
}

export interface PlayStatsResponse {
  total_plays: number;
  total_play_seconds: number;
  unique_tracks: number;
  top_tracks: Array<{
    id: string;
    title: string | null;
    artist: string | null;
    play_count: number;
    total_play_seconds: number;
    last_played_at: string | null;
  }>;
}

export const playTrackingApi = {
  recordPlay: async (trackId: string, durationSeconds?: number): Promise<PlayRecordResponse> => {
    const { data } = await api.post(`/tracks/${trackId}/played`, {
      duration_seconds: durationSeconds,
    });
    return data;
  },

  getStats: async (limit = 10): Promise<PlayStatsResponse> => {
    const { data } = await api.get('/tracks/stats/plays', { params: { limit } });
    return data;
  },
};

// Library Organization API
export interface OrganizeTemplate {
  name: string;
  template: string;
  example: string;
}

export interface OrganizeResult {
  track_id: string;
  old_path: string;
  new_path: string | null;
  status: 'moved' | 'skipped' | 'error';
  message: string;
}

export interface OrganizeStats {
  total: number;
  moved: number;
  skipped: number;
  errors: number;
  results: OrganizeResult[];
}

export const organizerApi = {
  getTemplates: async (): Promise<{ templates: OrganizeTemplate[] }> => {
    const { data } = await api.get('/library/organize/templates');
    return data;
  },

  preview: async (template: string, limit = 100): Promise<OrganizeStats> => {
    const { data } = await api.post('/library/organize/preview', { template, limit });
    return data;
  },

  run: async (template: string, dryRun = true): Promise<OrganizeStats> => {
    const { data } = await api.post('/library/organize/run', { template, dry_run: dryRun });
    return data;
  },

  previewTrack: async (trackId: string, template: string): Promise<OrganizeResult> => {
    const { data } = await api.get(`/library/organize/track/${trackId}/preview`, {
      params: { template },
    });
    return data;
  },

  organizeTrack: async (trackId: string, template: string, dryRun = false): Promise<OrganizeResult> => {
    const { data } = await api.post(`/library/organize/track/${trackId}`, {
      template,
      dry_run: dryRun,
    });
    return data;
  },
};

// Health/System Status API
export interface ServiceStatus {
  name: string;
  status: 'healthy' | 'degraded' | 'unhealthy';
  message: string | null;
  details: Record<string, unknown> | null;
}

export interface SystemHealth {
  status: 'healthy' | 'degraded' | 'unhealthy';
  services: ServiceStatus[];
  warnings: string[];
  deployment_mode: 'docker' | 'local';
  version: string;
}

export interface WorkerTask {
  id: string;
  name: string;
  args: unknown[];
  started_at: string | null;
}

export interface WorkerInfo {
  name: string;
  status: string;
  active_tasks: WorkerTask[];
  processed_total: number;
  concurrency: number | null;
}

export interface QueueStats {
  name: string;
  pending: number;
}

export interface TaskFailure {
  task: string;
  error: string;
  track: string | null;
  timestamp: string;
}

export interface WorkerStatus {
  workers: WorkerInfo[];
  queues: QueueStats[];
  analysis_progress: {
    total: number;
    analyzed: number;
    pending: number;
    percent: number;
  };
  recent_failures: TaskFailure[];
}

export const healthApi = {
  getSystemHealth: async (): Promise<SystemHealth> => {
    const { data } = await api.get('/health/system');
    return data;
  },

  getWorkerStatus: async (): Promise<WorkerStatus> => {
    const { data } = await api.get('/health/workers');
    return data;
  },
};

// Diagnostics API
export interface DiagnosticsExport {
  exported_at: string;
  version: string;
  deployment_mode: string;
  system_info: Record<string, unknown>;
  system_health: Record<string, unknown>;
  library_stats: Record<string, unknown>;
  recent_failures: Array<Record<string, unknown>>;
  recent_logs: Array<Record<string, unknown>>;
  settings_summary: Record<string, unknown>;
}

export const diagnosticsApi = {
  export: async (): Promise<DiagnosticsExport> => {
    const { data } = await api.get('/diagnostics/export');
    return data;
  },
};

// New Releases API
export interface NewReleasePurchaseLink {
  name: string;
  url: string;
}

export interface NewRelease {
  id: string;
  artist_name: string;
  release_name: string;
  release_type: string | null;
  release_date: string | null;
  artwork_url: string | null;
  external_url: string | null;
  track_count: number | null;
  source: 'spotify' | 'musicbrainz';
  local_album_match: boolean;
  dismissed: boolean;
  discovered_at: string;
  purchase_links: Record<string, NewReleasePurchaseLink>;
}

export interface NewReleasesListResponse {
  releases: NewRelease[];
  total: number;
  limit: number;
  offset: number;
}

export interface NewReleasesProgress {
  status: 'running' | 'completed' | 'error';
  phase: string;
  message: string;
  profile_id: string | null;
  artists_total: number;
  artists_checked: number;
  releases_found: number;
  releases_new: number;
  current_artist: string | null;
  started_at: string | null;
  errors: string[];
}

export interface NewReleasesStatus {
  total_releases_found: number;
  new_releases_available: number;
  artists_in_library: number;
  artists_checked: number;
  last_check_at: string | null;
  progress: NewReleasesProgress | null;
}

export interface NewReleasesCheckResponse {
  task_id: string;
  status: string;
  message: string;
}

export const newReleasesApi = {
  list: async (params?: {
    limit?: number;
    offset?: number;
    include_dismissed?: boolean;
    include_owned?: boolean;
  }): Promise<NewReleasesListResponse> => {
    const { data } = await api.get('/new-releases', { params });
    return data;
  },

  getStatus: async (): Promise<NewReleasesStatus> => {
    const { data } = await api.get('/new-releases/status');
    return data;
  },

  check: async (params?: {
    days_back?: number;
    force?: boolean;
  }): Promise<NewReleasesCheckResponse> => {
    const { data } = await api.post('/new-releases/check', null, { params });
    return data;
  },

  dismiss: async (releaseId: string): Promise<{ status: string; message: string }> => {
    const { data } = await api.post(`/new-releases/${releaseId}/dismiss`);
    return data;
  },
};

// Artwork prefetch API
export interface ArtworkQueueRequest {
  artist: string;
  album: string;
  track_id?: string;
}

export interface ArtworkQueueResponse {
  status: string;
  album_hash: string;
  message: string;
}

export interface ArtworkQueueBatchResponse {
  status: string;
  queued_count: number;
  existing_count: number;
  queued_hashes: string[];
}

export const artworkApi = {
  /**
   * Queue a single album for artwork download.
   * Returns immediately - artwork is fetched in background.
   */
  queue: async (request: ArtworkQueueRequest): Promise<ArtworkQueueResponse> => {
    const { data } = await api.post('/artwork/queue', request);
    return data;
  },

  /**
   * Queue multiple albums for artwork download.
   * Duplicates and existing artworks are filtered automatically.
   */
  queueBatch: async (
    items: ArtworkQueueRequest[]
  ): Promise<ArtworkQueueBatchResponse> => {
    const { data } = await api.post('/artwork/queue/batch', { items });
    return data;
  },

  /**
   * Check if artwork exists for an artist/album.
   * Uses HEAD request for efficiency.
   */
  checkExists: async (artist: string, album: string): Promise<boolean> => {
    try {
      await api.head(`/artwork/check/${encodeURIComponent(artist)}/${encodeURIComponent(album)}`);
      return true;
    } catch {
      return false;
    }
  },
};

// Background Jobs API
export interface JobProgress {
  current: number;
  total: number;
}

export interface BackgroundJob {
  type: 'library_sync' | 'spotify_sync' | 'new_releases' | 'artwork_fetch';
  status: 'running' | 'idle' | 'error' | 'complete';
  phase: string;
  progress: JobProgress | null;
  message: string;
  current_item: string | null;
  started_at: string | null;
}

export interface BackgroundJobsResponse {
  jobs: BackgroundJob[];
  active_count: number;
}

export const backgroundApi = {
  getJobs: async (): Promise<BackgroundJobsResponse> => {
    const { data } = await api.get('/background/jobs');
    return data;
  },
};

// Proposed Changes API
export type ChangeStatus = 'pending' | 'rejected' | 'applied';
export type ChangeSource = 'user_request' | 'llm_suggestion' | 'musicbrainz' | 'spotify' | 'auto_enrichment';
export type ChangeScope = 'db_only' | 'db_and_id3' | 'db_id3_files';

export interface ProposedChange {
  id: string;
  change_type: string;
  target_type: string;
  target_ids: string[];
  field: string | null;
  old_value: unknown;
  new_value: unknown;
  source: ChangeSource;
  source_detail: string | null;
  confidence: number;
  reason: string | null;
  scope: ChangeScope;
  status: ChangeStatus;
  created_at: string;
  applied_at: string | null;
}

export interface ChangePreview {
  change_id: string;
  target_description: string;
  field: string | null;
  old_value: unknown;
  new_value: unknown;
  tracks_affected: number;
  files_affected: string[];
  scope: ChangeScope;
}

export interface ApplyResult {
  change_id: string;
  success: boolean;
  error: string | null;
  db_updated: boolean;
  id3_written: boolean;
  id3_errors: string[];
  files_moved: boolean;
  files_errors: string[];
}

export interface ChangeStats {
  pending: number;
  rejected: number;
  applied: number;
}

export interface CreateChangeRequest {
  change_type: string;
  target_type: string;
  target_ids: string[];
  field?: string;
  old_value?: unknown;
  new_value: unknown;
  source?: string;
  source_detail?: string;
  confidence?: number;
  reason?: string;
  scope?: string;
}

export const proposedChangesApi = {
  list: async (params?: {
    status?: ChangeStatus;
    source?: ChangeSource;
    target_type?: string;
    limit?: number;
    offset?: number;
  }): Promise<ProposedChange[]> => {
    const { data } = await api.get('/proposed-changes/', { params });
    return data;
  },

  get: async (changeId: string): Promise<ProposedChange> => {
    const { data } = await api.get(`/proposed-changes/${changeId}`);
    return data;
  },

  getStats: async (): Promise<ChangeStats> => {
    const { data } = await api.get('/proposed-changes/stats');
    return data;
  },

  getTrackChanges: async (trackId: string): Promise<ProposedChange[]> => {
    const { data } = await api.get(`/proposed-changes/track/${trackId}`);
    return data;
  },

  preview: async (changeId: string): Promise<ChangePreview> => {
    const { data } = await api.get(`/proposed-changes/${changeId}/preview`);
    return data;
  },

  create: async (request: CreateChangeRequest): Promise<ProposedChange> => {
    const { data } = await api.post('/proposed-changes', request);
    return data;
  },

  reject: async (changeId: string): Promise<ProposedChange> => {
    const { data } = await api.post(`/proposed-changes/${changeId}/reject`);
    return data;
  },

  apply: async (changeId: string, scope?: ChangeScope): Promise<ApplyResult> => {
    const { data } = await api.post(`/proposed-changes/${changeId}/apply`, null, {
      params: scope ? { scope } : undefined,
    });
    return data;
  },

  undo: async (changeId: string): Promise<ApplyResult> => {
    const { data } = await api.post(`/proposed-changes/${changeId}/undo`);
    return data;
  },

  delete: async (changeId: string): Promise<{ status: string }> => {
    const { data } = await api.delete(`/proposed-changes/${changeId}`);
    return data;
  },

  batchApply: async (changeIds: string[], scope?: ChangeScope): Promise<ApplyResult[]> => {
    const { data } = await api.post('/proposed-changes/batch/apply', {
      change_ids: changeIds,
      scope,
    });
    return data;
  },
};

// Plugins API
export type PluginType = 'visualizer' | 'browser';

export interface PluginAuthor {
  name: string | null;
  url: string | null;
}

export interface Plugin {
  id: string;
  plugin_id: string;
  name: string;
  version: string;
  type: PluginType;
  description: string | null;
  author: PluginAuthor | null;
  repository_url: string;
  enabled: boolean;
  load_error: string | null;
  api_version: number;
  icon: string | null;
  preview: string | null;
}

export interface PluginListResponse {
  plugins: Plugin[];
  total: number;
}

export interface PluginInstallRequest {
  url: string;
}

export interface PluginInstallResponse {
  success: boolean;
  plugin_id: string | null;
  error: string | null;
}

export interface PluginUpdateCheckResponse {
  has_update: boolean;
  current_version: string;
  latest_version: string | null;
  error: string | null;
}

export const pluginsApi = {
  list: async (params?: {
    type?: PluginType;
    enabled_only?: boolean;
  }): Promise<PluginListResponse> => {
    const { data } = await api.get('/plugins', { params });
    return data;
  },

  get: async (pluginId: string): Promise<Plugin> => {
    const { data } = await api.get(`/plugins/${pluginId}`);
    return data;
  },

  install: async (url: string): Promise<PluginInstallResponse> => {
    const { data } = await api.post('/plugins/install', { url });
    return data;
  },

  update: async (
    pluginId: string,
    settings: { enabled?: boolean }
  ): Promise<Plugin> => {
    const { data } = await api.patch(`/plugins/${pluginId}`, settings);
    return data;
  },

  uninstall: async (pluginId: string): Promise<{ success: boolean }> => {
    const { data } = await api.delete(`/plugins/${pluginId}`);
    return data;
  },

  checkUpdate: async (pluginId: string): Promise<PluginUpdateCheckResponse> => {
    const { data } = await api.post(`/plugins/${pluginId}/check-update`);
    return data;
  },

  updateVersion: async (pluginId: string): Promise<PluginInstallResponse> => {
    const { data } = await api.post(`/plugins/${pluginId}/update`);
    return data;
  },

  reportError: async (
    pluginId: string,
    error: string
  ): Promise<{ success: boolean }> => {
    const { data } = await api.post(`/plugins/${pluginId}/report-error`, {
      error,
    });
    return data;
  },
};

// Export/Import API
export interface ExportRequest {
  include_play_history?: boolean;
  include_favorites?: boolean;
  include_playlists?: boolean;
  include_smart_playlists?: boolean;
  include_proposed_changes?: boolean;
  include_external_tracks?: boolean;
  chat_history?: Array<Record<string, unknown>>;
}

export interface ImportPreviewSummary {
  play_history_count: number;
  favorites_count: number;
  playlists_count: number;
  smart_playlists_count: number;
  proposed_changes_count: number;
  user_overrides_count: number;
  external_tracks_count: number;
  chat_history_count: number;
}

export interface ImportPreviewMatching {
  total: number;
  matched: number;
  unmatched: number;
  by_method: Record<string, number>;
  unmatched_samples: Array<{
    title: string | null;
    artist: string | null;
    album: string | null;
  }>;
}

export interface ImportPreviewResponse {
  session_id: string;
  summary: ImportPreviewSummary;
  matching: ImportPreviewMatching;
  warnings: string[];
  exported_at: string | null;
  familiar_version: string | null;
  profile_name: string | null;
}

export interface ImportExecuteRequest {
  session_id: string;
  mode: 'merge' | 'overwrite';
  import_play_history?: boolean;
  import_favorites?: boolean;
  import_playlists?: boolean;
  import_smart_playlists?: boolean;
  import_proposed_changes?: boolean;
  import_user_overrides?: boolean;
  import_external_tracks?: boolean;
}

export interface ImportResultCategory {
  imported: number;
  skipped: number;
  errors: string[];
}

export interface ImportExecuteResponse {
  status: string;
  results: {
    play_history: ImportResultCategory;
    favorites: ImportResultCategory;
    playlists: ImportResultCategory;
    smart_playlists: ImportResultCategory;
    proposed_changes: ImportResultCategory;
    user_overrides: ImportResultCategory;
    external_tracks: ImportResultCategory;
    chat_history: Array<Record<string, unknown>>;
  };
}

export const exportImportApi = {
  /**
   * Export profile data as JSON.
   * Returns the export data directly (caller should trigger download).
   */
  export: async (request: ExportRequest = {}): Promise<Record<string, unknown>> => {
    const { data } = await api.post('/export-import/export', request);
    return data;
  },

  /**
   * Download export as a file.
   * Creates a blob and triggers download in browser.
   */
  downloadExport: async (request: ExportRequest = {}): Promise<void> => {
    const data = await exportImportApi.export(request);

    // Generate filename
    const date = new Date().toISOString().split('T')[0].replace(/-/g, '');
    const filename = `familiar-export-${date}.json`;

    // Create blob and trigger download
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },

  /**
   * Preview an import file.
   * Returns matching statistics and a session_id for execution.
   */
  previewImport: async (file: File): Promise<ImportPreviewResponse> => {
    const formData = new FormData();
    formData.append('file', file);
    const { data } = await api.post('/export-import/import/preview', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return data;
  },

  /**
   * Execute an import from a previewed session.
   */
  executeImport: async (request: ImportExecuteRequest): Promise<ImportExecuteResponse> => {
    const { data } = await api.post('/export-import/import/execute', request);
    return data;
  },
};

// Library Export/Import API (for machine migration)
export interface LibraryExportRequest {
  include_embeddings?: boolean;
  include_acoustid?: boolean;
  compress?: boolean;
}

export interface LibraryImportPreviewSummary {
  total_tracks: number;
  tracks_with_analysis: number;
  tracks_with_embeddings: number;
  tracks_with_user_overrides: number;
  analysis_version: number | null;
}

export interface LibraryImportPreviewMatching {
  total: number;
  matched: number;
  unmatched: number;
  by_method: Record<string, number>;
  unmatched_samples: Array<{
    title: string | null;
    artist: string | null;
    album: string | null;
  }>;
}

export interface LibraryImportPreviewResponse {
  session_id: string;
  summary: LibraryImportPreviewSummary;
  matching: LibraryImportPreviewMatching;
  warnings: string[];
  exported_at: string | null;
  familiar_version: string | null;
}

export interface LibraryImportExecuteRequest {
  session_id: string;
  mode: 'match_only' | 'merge' | 'replace';
  apply_metadata?: boolean;
  apply_analysis?: boolean;
  apply_embeddings?: boolean;
  apply_user_overrides?: boolean;
}

export interface LibraryImportResults {
  analysis_imported: number;
  embeddings_imported: number;
  user_overrides_imported: number;
  metadata_updated: number;
  skipped: number;
  errors: string[];
}

export interface LibraryImportExecuteResponse {
  status: string;
  results: LibraryImportResults;
}

export const libraryExportApi = {
  /**
   * Download library export as a file.
   * Includes track metadata, analysis, embeddings, and user overrides.
   */
  downloadExport: async (
    request: LibraryExportRequest = {},
    onProgress?: (loaded: number, total: number) => void
  ): Promise<void> => {
    const response = await api.post('/export-import/library/export', request, {
      responseType: 'blob',
      timeout: 600000, // 10 minutes for large libraries
      onDownloadProgress: (progressEvent) => {
        if (onProgress && progressEvent.total) {
          onProgress(progressEvent.loaded, progressEvent.total);
        }
      },
    });

    // Extract filename from Content-Disposition header or generate one
    const contentDisposition = response.headers['content-disposition'];
    let filename = `familiar-library-export-${new Date().toISOString().split('T')[0].replace(/-/g, '')}`;

    if (contentDisposition) {
      const match = contentDisposition.match(/filename="?([^";\n]+)"?/);
      if (match) {
        filename = match[1];
      }
    } else {
      // Add extension based on compression
      filename += request.compress !== false ? '.json.gz' : '.json';
    }

    // Create blob and trigger download
    const blob = new Blob([response.data], {
      type: request.compress !== false ? 'application/gzip' : 'application/json',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },

  /**
   * Preview a library import file.
   * Returns matching statistics and a session_id for execution.
   */
  previewImport: async (
    file: File,
    onProgress?: (loaded: number, total: number) => void
  ): Promise<LibraryImportPreviewResponse> => {
    const formData = new FormData();
    formData.append('file', file);
    const { data } = await api.post('/export-import/library/import/preview', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000, // 5 minutes for large files
      onUploadProgress: (progressEvent) => {
        if (onProgress && progressEvent.total) {
          onProgress(progressEvent.loaded, progressEvent.total);
        }
      },
    });
    return data;
  },

  /**
   * Execute a library import from a previewed session.
   */
  executeImport: async (
    request: LibraryImportExecuteRequest
  ): Promise<LibraryImportExecuteResponse> => {
    const { data } = await api.post('/export-import/library/import/execute', request, {
      timeout: 600000, // 10 minutes for large imports
    });
    return data;
  },
};

// ============================================================================
// Backup/Restore API
// ============================================================================

export interface BackupRequest {
  // Profile data options
  include_play_history?: boolean;
  include_favorites?: boolean;
  include_playlists?: boolean;
  include_smart_playlists?: boolean;
  include_proposed_changes?: boolean;
  include_external_tracks?: boolean;
  // Library data options
  include_library_analysis?: boolean;
  include_embeddings?: boolean;
  include_acoustid?: boolean;
  // Output options
  compress?: boolean;
  // Optional chat history
  chat_history?: Array<Record<string, unknown>>;
}

export interface RestorePreviewSummary {
  has_profile_data: boolean;
  has_library_data: boolean;
  profile?: {
    play_history_count: number;
    favorites_count: number;
    playlists_count: number;
    smart_playlists_count: number;
    proposed_changes_count: number;
    user_overrides_count: number;
    external_tracks_count: number;
    chat_history_count: number;
  };
  library?: {
    total_tracks: number;
    tracks_with_analysis: number;
    tracks_with_embeddings: number;
    tracks_with_user_overrides: number;
    analysis_version: number | null;
  };
}

export interface RestorePreviewMatching {
  total: number;
  matched: number;
  unmatched: number;
  by_method: Record<string, number>;
  unmatched_samples: Array<{
    title: string | null;
    artist: string | null;
    album: string | null;
  }>;
}

export interface RestorePreviewResponse {
  session_id: string;
  summary: RestorePreviewSummary;
  profile_matching: RestorePreviewMatching;
  library_matching: RestorePreviewMatching;
  warnings: string[];
  exported_at: string | null;
  familiar_version: string | null;
  profile_name: string | null;
}

export interface RestoreExecuteRequest {
  session_id: string;
  // Profile import options
  mode: 'merge' | 'overwrite';
  import_play_history?: boolean;
  import_favorites?: boolean;
  import_playlists?: boolean;
  import_smart_playlists?: boolean;
  import_proposed_changes?: boolean;
  import_user_overrides?: boolean;
  import_external_tracks?: boolean;
  // Library import options
  library_mode?: 'match_only' | 'merge' | 'replace';
  apply_analysis?: boolean;
  apply_embeddings?: boolean;
  apply_library_user_overrides?: boolean;
}

export interface RestoreProfileResults {
  play_history: ImportResultCategory;
  favorites: ImportResultCategory;
  playlists: ImportResultCategory;
  smart_playlists: ImportResultCategory;
  proposed_changes: ImportResultCategory;
  user_overrides: ImportResultCategory;
  external_tracks: ImportResultCategory;
  chat_history: Array<Record<string, unknown>>;
}

export interface RestoreLibraryResults {
  analysis_imported: number;
  embeddings_imported: number;
  user_overrides_imported: number;
  skipped: number;
  errors: string[];
}

export interface RestoreExecuteResponse {
  status: string;
  results: {
    profile: RestoreProfileResults | null;
    library: RestoreLibraryResults | null;
  };
}

export const backupApi = {
  /**
   * Download a backup as a file.
   * Includes selected profile data and/or library analysis.
   */
  downloadBackup: async (
    request: BackupRequest = {},
    onProgress?: (loaded: number, total: number) => void
  ): Promise<void> => {
    const response = await api.post('/export-import/backup', request, {
      responseType: 'blob',
      timeout: 600000, // 10 minutes for large backups
      onDownloadProgress: (progressEvent) => {
        if (onProgress && progressEvent.total) {
          onProgress(progressEvent.loaded, progressEvent.total);
        }
      },
    });

    // Extract filename from Content-Disposition header or generate one
    const contentDisposition = response.headers['content-disposition'];
    let filename = `familiar-backup-${new Date().toISOString().split('T')[0].replace(/-/g, '')}`;

    if (contentDisposition) {
      const match = contentDisposition.match(/filename="?([^";\n]+)"?/);
      if (match) {
        filename = match[1];
      }
    } else {
      filename += request.compress !== false ? '.json.gz' : '.json';
    }

    // Create blob and trigger download
    const blob = new Blob([response.data], {
      type: request.compress !== false ? 'application/gzip' : 'application/json',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },

  /**
   * Preview a backup file for restore.
   */
  previewRestore: async (
    file: File,
    onProgress?: (loaded: number, total: number) => void
  ): Promise<RestorePreviewResponse> => {
    const formData = new FormData();
    formData.append('file', file);
    const { data } = await api.post('/export-import/restore/preview', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000, // 5 minutes for large files
      onUploadProgress: (progressEvent) => {
        if (onProgress && progressEvent.total) {
          onProgress(progressEvent.loaded, progressEvent.total);
        }
      },
    });
    return data;
  },

  /**
   * Execute a restore from a previewed session.
   */
  executeRestore: async (
    request: RestoreExecuteRequest
  ): Promise<RestoreExecuteResponse> => {
    const { data } = await api.post('/export-import/restore/execute', request, {
      timeout: 600000, // 10 minutes for large restores
    });
    return data;
  },
};

export default api;
