import api from './base';

// Health/System Status API
export interface AnalysisServiceDetails {
  total: number;
  analyzed: number;
  pending: number;
}

export interface BackgroundServiceDetails {
  sync_running: boolean;
  active_analyses: number;
  workers?: unknown[];
}

export type ServiceDetails =
  | AnalysisServiceDetails
  | BackgroundServiceDetails
  | Record<string, unknown>;

export interface ServiceStatus {
  name: string;
  status: 'healthy' | 'degraded' | 'unhealthy';
  message: string | null;
  details: ServiceDetails | null;
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

// Background Jobs API
export interface JobProgress {
  current: number;
  total: number;
}

export interface BackgroundJob {
  type: 'library_sync' | 'artwork_fetch' | 's3_backup' | 'spotify_matching';
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
    const { data } = await api.get('/admin/artists/merge-suggestions', {
      params: { limit },
    });
    return data;
  },

  mergeArtists: async (request: MergeArtistsRequest): Promise<MergeArtistsResponse> => {
    const { data } = await api.post('/admin/artists/merge', request);
    return data;
  },

  searchArtists: async (q: string, limit = 20): Promise<ArtistSearchResponse> => {
    const { data } = await api.get('/admin/artists/search', { params: { q, limit } });
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
