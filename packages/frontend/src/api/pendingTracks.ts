/**
 * Pending review tracks API client.
 */
import api from './base';

// ============================================================================
// Types
// ============================================================================

export interface PendingTrack {
  id: string;
  file_path: string;
  title: string | null;
  artist: string | null;
  album: string | null;
  album_artist: string | null;
  track_number: number | null;
  disc_number: number | null;
  year: number | null;
  genre: string | null;
  duration_seconds: number | null;
  format: string | null;
  sample_rate: number | null;
  bit_depth: number | null;
  bitrate: number | null;
  bitrate_mode: string | null;
  codec: string | null;
  created_at: string;
  review_info: {
    duplicate_of?: string;
    duplicate_info?: string;
    duplicate_match_type?: string;
    trump_status?: 'trumps' | 'trumped_by' | 'equal';
    trump_reason?: string;
    incoming_quality?: Record<string, unknown>;
    existing_quality?: Record<string, unknown>;
  } | null;
}

export interface PendingTrackGroup {
  folder_path: string;
  folder_name: string;
  track_count: number;
  duplicate_count: number;
  upgrade_count: number;
  downgrade_count: number;
  earliest_scan: string;
  tracks: PendingTrack[];
}

export interface PendingGroupsListResponse {
  groups: PendingTrackGroup[];
  total_groups: number;
  total_tracks: number;
}

export interface PendingTrackStats {
  total_tracks: number;
  total_groups: number;
  with_duplicates: number;
  upgrades: number;
  downgrades: number;
}

export interface ApproveRequest {
  metadata_overrides?: Record<string, unknown>;
  queue_analysis?: boolean;
}

export interface ReplaceRequest {
  replace_track_id: string;
  metadata_overrides?: Record<string, unknown>;
  queue_analysis?: boolean;
  transfer_user_data?: boolean;
}

export interface MetadataUpdate {
  artist?: string;
  album?: string;
  title?: string;
  track_number?: number;
  year?: number;
}

// ============================================================================
// API Functions
// ============================================================================

export const pendingTracksApi = {
  async listGroups(params?: {
    sort_by?: string;
    sort_order?: string;
    search?: string;
    status?: 'pending_review' | 'skipped';
    limit?: number;
    offset?: number;
  }): Promise<PendingGroupsListResponse> {
    const { data } = await api.get('/pending-tracks/groups', { params });
    return data;
  },

  async getStats(): Promise<PendingTrackStats> {
    const { data } = await api.get('/pending-tracks/stats');
    return data;
  },

  async approve(trackId: string, request?: ApproveRequest): Promise<void> {
    await api.post(`/pending-tracks/${trackId}/approve`, request ?? {});
  },

  async replace(trackId: string, request: ReplaceRequest): Promise<void> {
    await api.post(`/pending-tracks/${trackId}/replace`, request);
  },

  async skip(trackId: string): Promise<void> {
    await api.post(`/pending-tracks/${trackId}/skip`);
  },

  async unskip(trackId: string): Promise<void> {
    await api.post(`/pending-tracks/${trackId}/unskip`);
  },

  async updateMetadata(trackId: string, metadata: MetadataUpdate): Promise<void> {
    await api.patch(`/pending-tracks/${trackId}/metadata`, metadata);
  },

  async groupApprove(folderPath: string, opts?: { queue_analysis?: boolean; metadata_overrides?: Record<string, unknown> }): Promise<void> {
    await api.post('/pending-tracks/group/approve', { folder_path: folderPath, ...opts });
  },

  async groupSkip(folderPath: string): Promise<void> {
    await api.post('/pending-tracks/group/skip', { folder_path: folderPath });
  },

  async groupUnskip(folderPath: string): Promise<void> {
    await api.post('/pending-tracks/group/unskip', { folder_path: folderPath });
  },

  async groupReplaceUpgrades(folderPath: string, opts?: { queue_analysis?: boolean }): Promise<void> {
    await api.post('/pending-tracks/group/replace-upgrades', { folder_path: folderPath, ...opts });
  },

  async groupSkipDowngrades(folderPath: string): Promise<void> {
    await api.post('/pending-tracks/group/skip-downgrades', { folder_path: folderPath });
  },

  async groupMetadata(folderPath: string, metadata: Record<string, unknown>): Promise<void> {
    await api.post('/pending-tracks/group/metadata', { folder_path: folderPath, metadata });
  },

  async bulkApproveAll(opts?: { queue_analysis?: boolean }): Promise<void> {
    await api.post('/pending-tracks/bulk/approve-all', opts ?? {});
  },

  async bulkSkipAll(): Promise<void> {
    await api.post('/pending-tracks/bulk/skip-all');
  },

  async bulkUnskipAll(): Promise<void> {
    await api.post('/pending-tracks/bulk/unskip-all');
  },
};
