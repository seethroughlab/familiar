import type { Track, TrackListResponse } from '../types';
import api from './base';
import { getApiUrl } from './base';

// Track IDs response (lightweight for shuffle-all)
export interface TrackIdsResponse {
  ids: string[];
  total: number;
}

/** One visualizer offered for ranking, with whatever affinity it declared (ADR-0064). */
export interface VisualizerRankingCandidate {
  id: string;
  affinity?: {
    tags: string[];
    ranges: { feature: string; minimum?: number; maximum?: number }[];
  };
}

/** One visualizer's placing, and why. `ignored` is what the server did not recognise. */
export interface RankedVisualizer {
  id: string;
  score: number;
  matched_tags: string[];
  matched_ranges: string[];
  unmatched_ranges: string[];
  ignored: string[];
}

export interface VisualizerRankingResponse {
  visualizers: RankedVisualizer[];
  /**
   * False when the track has no analysis to rank against — an ordinary state on a library still
   * being analysed, **not** an error. The client must keep whatever it is showing rather than
   * pick, so `visualizers` comes back in the order it was submitted.
   */
  ranked: boolean;
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
    fx?: string;
    fx_min?: number;
    fx_max?: number;
    fy?: string;
    fy_min?: number;
    fy_max?: number;
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
    shuffle_preset?: string;
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
    fx?: string;
    fx_min?: number;
    fx_max?: number;
    fy?: string;
    fy_min?: number;
    fy_max?: number;
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

  /**
   * Ask the server which of *these* visualizers suits this track (ADR-0064).
   *
   * The candidates travel from the client because the server cannot know what is installed on a
   * device — ADR-0029 point 5 leaves device identity uninvented, and drop-in bundles live in a
   * directory on the device the server is never told about.
   */
  rankVisualizers: async (
    trackId: string,
    candidates: VisualizerRankingCandidate[]
  ): Promise<VisualizerRankingResponse> => {
    const { data } = await api.post(`/tracks/${trackId}/visualizer-ranking`, { candidates });
    return data;
  },

  getSimilar: async (id: string, limit = 10): Promise<Track[]> => {
    const { data } = await api.get(`/tracks/${id}/similar`, {
      params: { limit },
    });
    return data;
  },

  getStreamUrl: (id: string): string => {
    return getApiUrl(`/tracks/${id}/stream`);
  },

  getArtworkUrl: (id: string, size: 'full' | 'thumb' = 'full'): string => {
    return getApiUrl(`/tracks/${id}/artwork?size=${size}`);
  },

  getLyrics: async (id: string): Promise<LyricsResponse> => {
    const { data } = await api.get(`/tracks/${id}/lyrics`);
    return data;
  },

  reportPlaybackError: async (id: string): Promise<void> => {
    await api.post(`/tracks/${id}/report-playback-error`);
  },

  /**
   * Get the 0-based index of a track in the sorted/filtered list.
   * Used for auto-scrolling to the current track after navigation.
   */
  getIndex: async (
    id: string,
    params?: {
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
      fx?: string;
      fx_min?: number;
      fx_max?: number;
      fy?: string;
      fy_min?: number;
      fy_max?: number;
      sort_by?: string;
      sort_order?: 'asc' | 'desc';
    }
  ): Promise<{ index: number }> => {
    const { data } = await api.get(`/tracks/${id}/index`, { params });
    return data;
  },

  getAlbumGain: async (trackId: string): Promise<{ album_gain_db: number | null; album_peak: number | null; track_count: number }> => {
    const { data } = await api.get(`/tracks/${trackId}/album-gain`);
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

// Bulk edit types
export interface BulkEditErrorResponse {
  track_id: string;
  file_path: string;
  error: string;
}

export interface BulkEditResultResponse {
  total: number;
  successful: number;
  failed: number;
  errors: BulkEditErrorResponse[];
  fields_updated: string[];
}

export interface CommonValuesResponse {
  title: string | null;
  artist: string | null;
  album: string | null;
  album_artist: string | null;
  track_number: number | null;
  disc_number: number | null;
  year: number | null;
  genre: string | null;
  composer: string | null;
  conductor: string | null;
  lyricist: string | null;
  grouping: string | null;
  comment: string | null;
  sort_artist: string | null;
  sort_album: string | null;
  sort_title: string | null;
  lyrics: string | null;
  track_count: number;
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

  updateMetadata: async (
    trackIds: string[],
    metadata: Partial<TrackMetadataUpdate>,
  ): Promise<BulkEditResultResponse> => {
    const { data } = await api.post('/tracks/bulk/metadata', {
      track_ids: trackIds,
      metadata,
    });
    return data;
  },

  getCommonValues: async (trackIds: string[]): Promise<CommonValuesResponse> => {
    const { data } = await api.post('/tracks/bulk/common-values', {
      track_ids: trackIds,
    });
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
