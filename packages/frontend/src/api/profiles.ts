import api from './base';
import { getApiUrl } from './base';

// Profile API
export interface ProfileResponse {
  id: string;
  name: string;
  color: string | null;
  avatar_url: string | null;
  created_at: string;
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
    return getApiUrl(`/profiles/${id}/avatar`);
  },
};

// Favorites API
export interface FavoriteTrack {
  id: string;
  file_path: string;
  title: string | null;
  artist: string | null;
  album: string | null;
  album_artist: string | null;
  album_type: string;
  track_number: number | null;
  disc_number: number | null;
  year: number | null;
  genre: string | null;
  duration_seconds: number | null;
  format: string | null;
  analysis_version: number;
  favorited_at: string;
  last_played_at?: string | null;
  play_count?: number | null;
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

/** Why playback of a track stopped. Mirrors the backend `StopReason` (ADR-0004). */
export type ListenStopReason = 'natural' | 'user' | 'error';

/** Where the track was played from. Mirrors the backend `PlayContext`. */
export type ListenContext =
  | 'library' | 'album' | 'playlist' | 'artist'
  | 'ephemeral' | 'radio' | 'ambient' | 'other';

/** Body shared by /played, /skipped and /rejected. Every field is optional. */
export interface ListenEventBody {
  played_seconds?: number;
  track_duration?: number;
  completion_ratio?: number;
  context?: ListenContext;
  source_track_id?: string;
  reason?: ListenStopReason;
}

export interface ListenEventResponse {
  track_id: string;
  outcome: 'completed' | 'skipped' | 'rejected' | 'errored';
  completion_ratio: number;
}

export const playTrackingApi = {
  /**
   * Record a play. Bumps ProfilePlayHistory *and* writes a `completed` PlayEvent.
   *
   * Called only once scrobble thresholds are met, so reaching this endpoint is itself
   * the definition of a play — the backend does not derive the outcome here.
   */
  recordPlay: async (
    trackId: string,
    durationSeconds?: number,
    detail?: Omit<ListenEventBody, 'played_seconds' | 'reason'>,
  ): Promise<PlayRecordResponse> => {
    const { data } = await api.post(`/tracks/${trackId}/played`, {
      duration_seconds: durationSeconds,
      ...detail,
    });
    return data;
  },

  /**
   * Record that playback stopped before the track was scrobbled.
   *
   * Does NOT touch ProfilePlayHistory — only completed plays count toward it. The
   * backend derives the outcome, so a track abandoned at 95%, or a short one played in
   * full, comes back `completed` rather than `skipped`.
   */
  recordSkip: async (trackId: string, body: ListenEventBody = {}): Promise<ListenEventResponse> => {
    const { data } = await api.post(`/tracks/${trackId}/skipped`, body);
    return data;
  },

  /**
   * Record an explicit thumbs-down — a stronger signal than a skip, and stored
   * distinctly. Intended for radio insertions (ADR-0005); no UI triggers it yet.
   */
  recordRejection: async (trackId: string, body: ListenEventBody = {}): Promise<ListenEventResponse> => {
    const { data } = await api.post(`/tracks/${trackId}/rejected`, body);
    return data;
  },

  getStats: async (limit = 10): Promise<PlayStatsResponse> => {
    const { data } = await api.get('/tracks/stats/plays', { params: { limit } });
    return data;
  },
};
