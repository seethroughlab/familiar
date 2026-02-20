import api from './base';

// New Releases API
export interface NewReleasePurchaseLink {
  name: string;
  url: string;
}

export interface NewRelease {
  id: string;
  artist_name: string;
  release_name: string;
  release_type: string | null;
  release_date: string | null;
  artwork_url: string | null;
  external_url: string | null;
  track_count: number | null;
  source: 'spotify' | 'musicbrainz';
  local_album_match: boolean;
  dismissed: boolean;
  discovered_at: string;
  purchase_links: Record<string, NewReleasePurchaseLink>;
}

export interface NewReleasesListResponse {
  releases: NewRelease[];
  total: number;
  limit: number;
  offset: number;
}

export interface NewReleasesProgress {
  status: 'running' | 'completed' | 'error';
  phase: string;
  message: string;
  profile_id: string | null;
  artists_total: number;
  artists_checked: number;
  releases_found: number;
  releases_new: number;
  current_artist: string | null;
  started_at: string | null;
  errors: string[];
}

export interface NewReleasesStatus {
  total_releases_found: number;
  new_releases_available: number;
  artists_in_library: number;
  artists_checked: number;
  last_check_at: string | null;
  progress: NewReleasesProgress | null;
}

export interface NewReleasesCheckResponse {
  task_id: string;
  status: string;
  message: string;
}

export const newReleasesApi = {
  list: async (params?: {
    limit?: number;
    offset?: number;
    include_dismissed?: boolean;
    include_owned?: boolean;
  }): Promise<NewReleasesListResponse> => {
    const { data } = await api.get('/new-releases', { params });
    return data;
  },

  getStatus: async (): Promise<NewReleasesStatus> => {
    const { data } = await api.get('/new-releases/status');
    return data;
  },

  check: async (params?: {
    days_back?: number;
    force?: boolean;
  }): Promise<NewReleasesCheckResponse> => {
    const { data } = await api.post('/new-releases/check', null, { params });
    return data;
  },

  dismiss: async (releaseId: string): Promise<{ status: string; message: string }> => {
    const { data } = await api.post(`/new-releases/${releaseId}/dismiss`);
    return data;
  },
};
