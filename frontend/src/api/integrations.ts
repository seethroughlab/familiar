import api from './base';

export interface SpotifyStatus {
  configured: boolean;
  connected: boolean;
  spotify_user_id: string | null;
  last_sync: string | null;
  stats: {
    total_favorites: number;
    matched: number;
    unmatched: number;
    match_rate: number;
  } | null;
}

export interface SpotifySyncResponse {
  status: string;
  message: string;
  stats?: {
    fetched: number;
    new: number;
    matched: number;
    unmatched: number;
  };
  progress?: SpotifySyncProgress | null;
}

export interface SpotifySyncProgress {
  phase: string;
  tracks_fetched: number;
  tracks_processed: number;
  tracks_total: number;
  new_favorites: number;
  matched: number;
  unmatched: number;
  current_track: string | null;
  started_at: string | null;
  errors: string[];
}

export interface StoreSearchLink {
  name: string;
  url: string;
}

export interface UnmatchedTrack {
  spotify_id: string;
  name: string | null;
  artist: string | null;
  album: string | null;
  added_at: string | null;
  popularity: number | null;
  search_links: Record<string, StoreSearchLink>;
}

export const spotifyApi = {
  getStatus: async (): Promise<SpotifyStatus> => {
    const { data } = await api.get('/spotify/status');
    return data;
  },

  getAuthUrl: async (): Promise<{ auth_url: string; state: string }> => {
    const { data } = await api.get('/spotify/auth');
    return data;
  },

  sync: async (includeTopTracks = true, favoriteMatched = false): Promise<SpotifySyncResponse> => {
    const { data } = await api.post('/spotify/sync', null, {
      params: { include_top_tracks: includeTopTracks, favorite_matched: favoriteMatched },
      timeout: 300000, // 5 minute timeout for large libraries
    });
    return data;
  },

  disconnect: async (): Promise<{ status: string }> => {
    const { data } = await api.post('/spotify/disconnect');
    return data;
  },

  getSyncStatus: async (): Promise<SpotifySyncResponse> => {
    const { data } = await api.get('/spotify/sync/status');
    return data;
  },

  getUnmatched: async (params?: {
    limit?: number;
    sort_by?: 'popularity' | 'added_at';
  }): Promise<UnmatchedTrack[]> => {
    const { data } = await api.get('/spotify/unmatched', { params });
    return data;
  },
};

export interface VideoSearchResult {
  video_id: string;
  title: string;
  channel: string;
  duration: number;
  thumbnail_url: string;
  url: string;
}

export interface VideoStatus {
  has_video: boolean;
  download_status: string | null;
  progress: number | null;
  error: string | null;
}

export const videosApi = {
  search: async (trackId: string, limit = 5): Promise<VideoSearchResult[]> => {
    const { data } = await api.get(`/videos/${trackId}/search`, {
      params: { limit },
    });
    return data;
  },

  getStatus: async (trackId: string): Promise<VideoStatus> => {
    const { data } = await api.get(`/videos/${trackId}/status`);
    return data;
  },

  download: async (trackId: string, videoUrl: string): Promise<{ status: string; message: string }> => {
    const { data } = await api.post(`/videos/${trackId}/download`, {
      video_url: videoUrl,
    });
    return data;
  },

  getStreamUrl: (trackId: string): string => {
    return `/api/v1/videos/${trackId}/stream`;
  },

  delete: async (trackId: string): Promise<{ status: string }> => {
    const { data } = await api.delete(`/videos/${trackId}`);
    return data;
  },
};

export interface LastfmStatus {
  configured: boolean;
  connected: boolean;
  username: string | null;
}

export const lastfmApi = {
  getStatus: async (): Promise<LastfmStatus> => {
    const { data } = await api.get('/lastfm/status');
    return data;
  },

  getAuthUrl: async (): Promise<{ auth_url: string }> => {
    const { data } = await api.get('/lastfm/auth');
    return data;
  },

  callback: async (token: string): Promise<{ status: string; username: string }> => {
    const { data } = await api.post('/lastfm/callback', null, {
      params: { token },
    });
    return data;
  },

  disconnect: async (): Promise<{ status: string }> => {
    const { data } = await api.post('/lastfm/disconnect');
    return data;
  },

  updateNowPlaying: async (trackId: string): Promise<{ status: string; message: string }> => {
    const { data } = await api.post('/lastfm/now-playing', { track_id: trackId });
    return data;
  },

  scrobble: async (trackId: string, timestamp?: number): Promise<{ status: string; message: string }> => {
    const { data } = await api.post('/lastfm/scrobble', {
      track_id: trackId,
      timestamp,
    });
    return data;
  },
};

// Spotify Playlist Import API
export interface SpotifyPlaylistInfo {
  id: string;
  name: string;
  description: string | null;
  track_count: number;
  image_url: string | null;
  external_url: string | null;
  owner: string | null;
  public: boolean | null;
}

export interface SpotifyPlaylistTrack {
  spotify_id: string;
  title: string;
  artist: string | null;
  album: string | null;
  duration_ms: number | null;
  preview_url: string | null;
  in_library: boolean;
  local_track_id: string | null;
}

export interface SpotifyPlaylistTracksResponse {
  playlist_name: string;
  playlist_description: string | null;
  tracks: SpotifyPlaylistTrack[];
  total: number;
  in_library: number;
  missing: number;
  match_rate: string;
}

export interface ImportedPlaylist {
  id: string;
  name: string;
  description: string | null;
  track_count: number;
}

export const spotifyPlaylistsApi = {
  list: async (limit = 50): Promise<SpotifyPlaylistInfo[]> => {
    const { data } = await api.get('/spotify/playlists', { params: { limit } });
    return data;
  },

  getTracks: async (
    playlistId: string,
    limit = 100
  ): Promise<SpotifyPlaylistTracksResponse> => {
    const { data } = await api.get(`/spotify/playlists/${playlistId}/tracks`, {
      params: { limit },
    });
    return data;
  },

  import: async (
    playlistId: string,
    options?: {
      name?: string;
      description?: string;
      include_missing?: boolean;
    }
  ): Promise<ImportedPlaylist> => {
    const { data } = await api.post(`/spotify/playlists/${playlistId}/import`, options);
    return data;
  },
};
