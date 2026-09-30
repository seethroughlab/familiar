import api from './base';

// Diagnostics API
export interface DiagnosticsExport {
  exported_at: string;
  version: string;
  deployment_mode: string;
  /** Variable system info (OS, hardware, Python version, etc.) — shape depends on host. */
  system_info: Record<string, unknown>;
  /** Full health snapshot — shape mirrors SystemHealth but serialized as plain object. */
  system_health: Record<string, unknown>;
  /** Library statistics — shape varies by analysis version and enabled features. */
  library_stats: Record<string, unknown>;
  /** Recent task failures — each entry's shape depends on the failing task type. */
  recent_failures: Array<Record<string, unknown>>;
  /** Recent log entries — each entry's shape depends on the log handler configuration. */
  recent_logs: Array<Record<string, unknown>>;
  /** Scrubbed settings — shape varies as new settings are added. */
  settings_summary: Record<string, unknown>;
}

export const diagnosticsApi = {
  export: async (): Promise<DiagnosticsExport> => {
    const { data } = await api.get('/diagnostics/export');
    return data;
  },
};


// Admin: canonical artist merge
export interface MergeCandidate {
  id: string;
  name: string;
  sort_name: string;
  track_count: number;
  musicbrainz_id: string | null;
}

export interface MergeSuggestion {
  canonical_form: string;
  suggested_keep_id: string;
  candidates: MergeCandidate[];
}

export interface MergeSuggestionsResponse {
  suggestions: MergeSuggestion[];
}

export interface MergeArtistsRequest {
  keep_id: string;
  merge_ids: string[];
}

export interface MergeArtistsResponse {
  kept_artist_id: string;
  aliases_moved: number;
  aliases_dropped_as_duplicates: number;
  tracks_repointed: number;
  artists_deleted: number;
}

export interface ArtistSearchResult {
  id: string;
  name: string;
  sort_name: string;
  track_count: number;
  musicbrainz_id: string | null;
}

export interface ArtistSearchResponse {
  results: ArtistSearchResult[];
}

export const adminArtistsApi = {
  getMergeSuggestions: async (limit = 100): Promise<MergeSuggestionsResponse> => {
    const { data } = await api.get('/artists/merge-suggestions', {
      params: { limit },
    });
    return data;
  },

  mergeArtists: async (request: MergeArtistsRequest): Promise<MergeArtistsResponse> => {
    const { data } = await api.post('/artists/merge', request);
    return data;
  },

  searchArtists: async (q: string, limit = 20): Promise<ArtistSearchResponse> => {
    const { data } = await api.get('/artists/search', { params: { q, limit } });
    return data;
  },
};

// Update Notifications API
export interface UpdateStatus {
  update_available: boolean;
  current_version: string;
  latest_version: string | null;
  release_url: string | null;
  release_name: string | null;
  published_at: string | null;
  channel: string;
  checked_at: string | null;
  error?: string | null;
}

export const updatesApi = {
  getStatus: async (): Promise<UpdateStatus> => {
    const { data } = await api.get('/updates');
    return data;
  },

  checkNow: async (): Promise<UpdateStatus> => {
    const { data } = await api.post('/updates/check');
    return data;
  },
};
