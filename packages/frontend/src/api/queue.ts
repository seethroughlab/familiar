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

export const queueApi = {
  getSuggestions: async (request: QueueSuggestionsRequest): Promise<QueueSuggestionsResponse> => {
    const { data } = await api.post('/queue/suggestions', request);
    return data;
  },
};
