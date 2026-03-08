import api from './base';

export interface MissingTrack {
  id: string;
  title: string | null;
  artist: string | null;
  album: string | null;
  file_path: string;
  status: 'missing' | 'pending_deletion';
  missing_since: string | null;
  days_missing: number;
}

export interface MissingTracksResponse {
  tracks: MissingTrack[];
  total_missing: number;
  total_pending_deletion: number;
}

export interface MissingTracksRelocateResponse {
  found: number;
  not_found: number;
}

export interface MissingTracksDeleteBatchResponse {
  deleted: number;
}

export const missingTracksApi = {
  list: async (): Promise<MissingTracksResponse> => {
    const { data } = await api.get('/library/missing');
    return data;
  },

  relocateBatch: async (searchPath: string): Promise<MissingTracksRelocateResponse> => {
    const { data } = await api.post('/library/missing/relocate', {
      search_path: searchPath,
    });
    return data;
  },

  locateTrack: async (trackId: string, newPath: string): Promise<void> => {
    await api.post(`/library/missing/${trackId}/locate`, {
      new_path: newPath,
    });
  },

  deleteTrack: async (trackId: string): Promise<void> => {
    await api.delete(`/library/missing/${trackId}`);
  },

  deleteBatch: async (trackIds: string[]): Promise<MissingTracksDeleteBatchResponse> => {
    const { data } = await api.delete('/library/missing/batch', {
      data: { track_ids: trackIds },
    });
    return data;
  },
};
