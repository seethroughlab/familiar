import api from './base';

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
  // S3 Backup
  s3_backup_enabled: boolean;
  s3_backup_bucket: string | null;
  s3_backup_region: string;
  s3_backup_prefix: string;
  s3_backup_schedule: string;
  s3_backup_configured: boolean;
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
  // S3 Backup
  s3_backup_enabled?: boolean;
  s3_backup_schedule?: string;
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
  target_description: string | null;
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
