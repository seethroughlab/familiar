/**
 * Queue API client — suggestions (ADR-0005), offline manifests (ADR-0006) and the
 * server-owned playback session (ADR-0003).
 */

import api from './base';
import type { RequestOptions } from './base';
import type { Track } from '../types';
import type { QueueSource } from '../player/playerStore.types';

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

/**
 * The durable queue as the server holds it (ADR-0003).
 *
 * `queue_source` is aliased to the player's own `QueueSource` rather than restated, so the
 * wire type and the store cannot drift — the server deliberately accepts only the client's
 * queue-source vocabulary, not the wider `PlayContext`.
 */
export interface PlaybackSessionBody {
  track_ids: string[];
  cursor: number;
  shuffle_order: number[];
  shuffle_index: number;
  shuffle: boolean;
  repeat: 'off' | 'all' | 'one';
  consume: boolean;
  queue_source: QueueSource | null;
  /** Omit to mean "unchanged, and it hashes to `reservoir_hash`". */
  reservoir_ids?: string[] | null;
  reservoir_cursor: number;
  reservoir_hash?: string | null;
  position_seconds: number;
}

export interface PlaybackSessionWrite extends PlaybackSessionBody {
  /** The version this write is based on. A mismatch is what the server treats as a conflict. */
  version: number;
  /** The client's own clock — the server cannot know when an offline edit happened. */
  updated_at?: string | null;
}

export interface PlaybackSessionResponse extends PlaybackSessionBody {
  version: number;
  updated_at: string;
  /** True when this write lost a conflict and the body is the other device's queue. */
  superseded: boolean;
}

export interface ArchivedSession {
  id: string;
  track_ids: string[];
  cursor: number;
  queue_source: QueueSource | null;
  position_seconds: number;
  superseded_at: string;
  archived_at: string;
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

  getSession: async (): Promise<PlaybackSessionResponse> => {
    const { data } = await api.get('/queue/session');
    return data;
  },

  /**
   * Upsert the durable queue.
   *
   * Rejects with a 409 when `reservoir_ids` was omitted but the named hash does not match
   * what the server holds; the caller should resend with the reservoir in full.
   */
  putSession: async (
    session: PlaybackSessionWrite,
    options?: RequestOptions,
  ): Promise<PlaybackSessionResponse> => {
    const { data } = await api.put('/queue/session', session, options);
    return data;
  },

  listArchivedSessions: async (): Promise<{ sessions: ArchivedSession[] }> => {
    const { data } = await api.get('/queue/session/archive');
    return data;
  },

  restoreArchivedSession: async (archiveId: string): Promise<PlaybackSessionResponse> => {
    const { data } = await api.post(`/queue/session/archive/${archiveId}/restore`);
    return data;
  },
};
