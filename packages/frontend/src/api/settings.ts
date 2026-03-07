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
  anthropic_configured: boolean;
  acoustid_configured: boolean;
  // Community cache
  community_cache_enabled: boolean;
  community_cache_contribute: boolean;
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
  // Update notifications
  update_channel: string;
}

export interface AppSettingsUpdate {
  spotify_client_id?: string;
  spotify_client_secret?: string;
  lastfm_api_key?: string;
  lastfm_api_secret?: string;
  anthropic_api_key?: string;
  // Community cache
  community_cache_enabled?: boolean;
  community_cache_contribute?: boolean;
  // Analysis settings
  clap_embeddings_enabled?: boolean | null;
  // Playlist generation
  playlist_discovery_mode?: string;
  // S3 Backup
  s3_backup_enabled?: boolean;
  s3_backup_schedule?: string;
  // Update notifications
  update_channel?: string;
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
