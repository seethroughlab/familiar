import api from './base';
import { encodePathSegment } from './base';

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

  previewTrack: async (trackId: string, template: string): Promise<OrganizeResult> => {
    const { data } = await api.get(`/library/organize/track/${trackId}/preview`, {
      params: { template },
    });
    return data;
  },

};

// Artwork prefetch API
export interface ArtworkQueueRequest {
  artist: string;
  album: string;
  track_id?: string;
}

export interface ArtworkQueueResponse {
  status: string;
  album_hash: string;
  message: string;
}

/** What the server decided for one album in a batch. */
export interface ArtworkQueueBatchResult {
  artist: string | null;
  album: string | null;
  /**
   * The album's artwork key, as decided by the server.
   *
   * Since ADR-0052 this is an `Album.id`, which nothing in a browser could derive.
   * Before it, the client reimplemented `normalize_for_matching` and SHA-256 in
   * JavaScript to guess it — see the deleted `utils/albumHash.ts`.
   */
  album_key: string;
  status: 'queued' | 'exists' | 'pending' | 'skipped' | 'duplicate';
}

export interface ArtworkQueueBatchResponse {
  status: string;
  queued_count: number;
  existing_count: number;
  queued_hashes: string[];
  existing_hashes: string[];
  pending_hashes: string[];
  /** Per-item outcome. Prefer this over the three flat arrays. */
  results?: ArtworkQueueBatchResult[];
}

export interface ArtworkStatusBatchResponse {
  status: Record<string, boolean>;
  failed: string[];
}

export interface ArtworkUploadResponse {
  status: string;
  message: string;
}

export const artworkApi = {
  /**
   * Queue a single album for artwork download.
   * Returns immediately - artwork is fetched in background.
   */
  queue: async (request: ArtworkQueueRequest): Promise<ArtworkQueueResponse> => {
    const { data } = await api.post('/artwork/queue', request);
    return data;
  },

  /**
   * Queue multiple albums for artwork download.
   * Duplicates and existing artworks are filtered automatically.
   */
  queueBatch: async (
    items: ArtworkQueueRequest[]
  ): Promise<ArtworkQueueBatchResponse> => {
    const { data } = await api.post('/artwork/queue/batch', { items });
    return data;
  },

  /**
   * Check if artwork exists for an artist/album.
   * Uses HEAD request for efficiency.
   */
  statusBatch: async (hashes: string[]): Promise<ArtworkStatusBatchResponse> => {
    const { data } = await api.post('/artwork/status/batch', { hashes });
    return data;
  },

  uploadTrackArtwork: async (
    trackId: string,
    file: File,
    embedInFile: boolean,
  ): Promise<ArtworkUploadResponse> => {
    const formData = new FormData();
    formData.append('file', file);
    const { data } = await api.post(
      `/tracks/${trackId}/artwork?embed_in_file=${embedInFile}`,
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    );
    return data;
  },

  checkExists: async (artist: string, album: string): Promise<boolean> => {
    try {
      await api.head(`/artwork/check/${encodePathSegment(artist)}/${encodePathSegment(album)}`);
      return true;
    } catch {
      return false;
    }
  },
};

// Proposed Changes API
export type ChangeStatus = 'pending' | 'rejected' | 'applied';
export type ChangeSource = 'user_request' | 'llm_suggestion' | 'musicbrainz' | 'spotify';
export type ChangeScope = 'db_only';

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

  apply: async (changeId: string): Promise<ApplyResult> => {
    const { data } = await api.post(`/proposed-changes/${changeId}/apply`);
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

  batchApply: async (changeIds: string[]): Promise<ApplyResult[]> => {
    const { data } = await api.post('/proposed-changes/batch/apply', {
      change_ids: changeIds,
    });
    return data;
  },

  scan: async (): Promise<{ created: number }> => {
    const { data } = await api.post('/proposed-changes/scan');
    return data;
  },
};
