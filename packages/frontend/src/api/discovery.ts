/**
 * Discovery API: new releases (#3) + external albums (per-playlist + listening-profile).
 *
 * Backend surfaces:
 * - `/new-releases/*` — Pass 1
 * - `/external-albums/{id}/dismiss` — generic dismiss (works for any context)
 * - `/library/discover/external-albums` — listening-profile recommendations (Pass 2.5)
 * - `/playlists/{id}/recommendations/external-albums` — per-playlist (used in Pass 4)
 */
import api from './base';

// ============================================================================
// Shared external-album shape
// ============================================================================

export interface ExternalAlbum {
  id: string;
  artist_name: string;
  release_name: string;
  release_type: string | null;
  release_date: string | null;
  artwork_url: string;
  external_url: string | null;
  track_count: number | null;
  match_score?: number;
  seed_artist?: string | null;
  local_album_match: boolean;
  dismissed: boolean;
  discovered_at: string;
  purchase_links: Record<string, { name: string; url: string }>;
}

// ============================================================================
// New releases (#3)
// ============================================================================

export interface NewReleasesProgress {
  status: 'running' | 'completed' | 'error' | string;
  phase?: string;
  message?: string;
  artists_total?: number;
  artists_checked?: number;
  releases_found?: number;
  releases_new?: number;
  current_artist?: string | null;
  started_at?: string;
  last_heartbeat?: string;
  errors?: string[];
}

export interface NewReleasesRotation {
  total_artists_in_rotation: number;
  checked_this_week: number;
  remaining_this_week: number;
  estimated_days_to_complete: number;
}

export interface NewReleasesStatus {
  total_releases_found: number;
  new_releases_available: number;
  artists_in_library: number;
  artists_checked: number;
  last_check_at: string | null;
  progress: NewReleasesProgress | null;
  rotation: NewReleasesRotation;
}

export interface NewReleasesListResponse {
  releases: ExternalAlbum[];
  total: number;
  limit: number;
  offset: number;
}

export interface NewReleasesListParams {
  limit?: number;
  offset?: number;
  include_dismissed?: boolean;
  include_owned?: boolean;
}

export const newReleasesApi = {
  async list(params?: NewReleasesListParams): Promise<NewReleasesListResponse> {
    const { data } = await api.get('/new-releases', { params });
    return data;
  },

  async getStatus(): Promise<NewReleasesStatus> {
    const { data } = await api.get('/new-releases/status');
    return data;
  },

  async check(params?: { days_back?: number; force?: boolean }): Promise<{ status: string; message: string }> {
    const { data } = await api.post('/new-releases/check', null, { params });
    return data;
  },

  async checkBatch(params?: { batch_size?: number; days_back?: number }): Promise<{ status: string; message: string }> {
    const { data } = await api.post('/new-releases/check/batch', null, { params });
    return data;
  },
};

// ============================================================================
// External albums (generic dismiss + listening-profile + per-playlist)
// ============================================================================

export interface ExternalAlbumsResponse {
  albums: ExternalAlbum[];
}

export const externalAlbumsApi = {
  async dismiss(externalAlbumId: string): Promise<void> {
    await api.post(`/external-albums/${externalAlbumId}/dismiss`);
  },

  /** Listening-profile (#2 in Discover) — seeded by user's top-played artists. */
  async listeningProfile(params?: { limit?: number; refresh?: boolean }): Promise<ExternalAlbumsResponse> {
    const { data } = await api.get('/library/discover/external-albums', { params });
    return data;
  },

  /** Per-playlist (#2 in playlist drawer, Pass 4). */
  async forPlaylist(
    playlistId: string,
    params?: { limit?: number; refresh?: boolean },
  ): Promise<ExternalAlbumsResponse> {
    const { data } = await api.get(
      `/playlists/${playlistId}/recommendations/external-albums`,
      { params },
    );
    return data;
  },
};
