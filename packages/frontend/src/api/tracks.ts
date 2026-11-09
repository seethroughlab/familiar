import type * as Wire from '@familiar/api-client';
import type { Track, TrackListResponse } from '../types';
import api from './base';
import { getApiUrl } from './base';

// Track IDs response (lightweight for shuffle-all)
export type TrackIdsResponse = Wire.TrackIdsResponse;

/** One visualizer offered for ranking, with whatever affinity it declared (ADR-0064). */
export type VisualizerRankingCandidate = Wire.VisualizerCandidate;

/** One visualizer's placing, and why. `ignored` is what the server did not recognise. */
export type RankedVisualizer = Wire.RankedVisualizer;

export type VisualizerRankingResponse = Wire.VisualizerRankingResponse;

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
export type IdentifyCandidate = Wire.IdentifyCandidateResponse;

export type IdentifyTrackResponse = Wire.IdentifyTrackResponse;

// Bulk identification types
export type BulkIdentifyTaskResponse = Wire.BulkIdentifyTaskResponse;

export type BulkIdentifyProgress = Wire.BulkIdentifyProgress;

// Bulk edit types
export type BulkEditErrorResponse = Wire.BulkEditErrorResponse;

export type BulkEditResultResponse = Wire.BulkEditResultResponse;

export type CommonValuesResponse = Wire.CommonValuesResponse;

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
export type TrackMetadataUpdate = Wire.TrackMetadataUpdateRequest;

export type TrackMetadataResponse = Wire.TrackMetadataResponse;

export type LyricLine = Wire.LyricLineResponse;

export type LyricsResponse = Wire.LyricsResponse;

export type TrackDiscoverSimilarArtist = Wire.SimilarArtistInfo;

export type TrackDiscoverResponse = Wire.TrackDiscoverResponse;
