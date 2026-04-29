import api, { getApiUrl } from './base';

export type MixTapeStatus = 'pending' | 'rendering' | 'ready' | 'failed';

export interface MixTapeProgress {
  status: MixTapeStatus;
  phase?: string;
  progress?: number;
  error?: string;
}

export interface MixTape {
  id: string;
  name: string;
  byline: string | null;
  source_playlist_id: string | null;
  source_smart_playlist_id: string | null;
  track_ids: string[];
  crossfade_seconds: number | null;
  status: MixTapeStatus;
  error_message: string | null;
  duration_seconds: number | null;
  file_size_bytes: number | null;
  created_at: string;
  completed_at: string | null;
  progress?: MixTapeProgress | null;
}

export interface MixTapeCreateRequest {
  name: string;
  source_playlist_id?: string;
  source_smart_playlist_id?: string;
  crossfade_seconds?: number | null;
  byline?: string | null;
}

function triggerBlobDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export const mixtapesApi = {
  create: async (request: MixTapeCreateRequest): Promise<MixTape> => {
    const response = await api.post('/mixtapes', request);
    return response.data;
  },

  list: async (): Promise<MixTape[]> => {
    const response = await api.get('/mixtapes');
    return response.data;
  },

  get: async (id: string): Promise<MixTape> => {
    const response = await api.get(`/mixtapes/${id}`);
    return response.data;
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/mixtapes/${id}`);
  },

  download: async (id: string, name: string): Promise<void> => {
    const response = await api.get(`/mixtapes/${id}/download`, {
      responseType: 'blob',
      timeout: 300000,
    });
    triggerBlobDownload(response.data, `${name}.zip`);
  },

  /** URL pointing at the bundle endpoint — useful for native share sheets in v2. */
  downloadUrl: (id: string): string => getApiUrl(`/mixtapes/${id}/download`),
};
