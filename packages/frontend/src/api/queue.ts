/**
 * Queue suggestion API client (ADR-0005).
 */

import api from './base';
import type { Track } from '../types';

export interface QueueSuggestionsRequest {
  current_track_id: string;
  recent_track_ids?: string[];
  recent_artist_names?: string[];
  profile?: 'radio' | 'ambient';
  limit?: number;
}

export interface QueueSuggestion {
  track: Track;
  score: number;
}

export interface QueueSuggestionsResponse {
  suggestions: QueueSuggestion[];
  pool_size: number;
  pool_collapsed: boolean;
}

export interface OfflineManifestRequest {
  track_ids: string[];
  neighbours?: number;
}

export interface OfflineManifestVariantResponse {
  profile: string;
  filter_preset: string;
  entries: { track_id: string; neighbours: { track_id: string; score: number }[] }[];
  seed_track_ids: string[];
}

export interface OfflineManifestResponse {
  variants: OfflineManifestVariantResponse[];
  track_count: number;
}

export const queueApi = {
  getOfflineManifest: async (
    request: OfflineManifestRequest
  ): Promise<OfflineManifestResponse> => {
    const { data } = await api.post('/queue/offline-manifest', request);
    return data;
  },

  getSuggestions: async (request: QueueSuggestionsRequest): Promise<QueueSuggestionsResponse> => {
    const { data } = await api.post('/queue/suggestions', request);
    return data;
  },
};
