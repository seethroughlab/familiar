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
  search_links: Record<string, StoreSearchLink>;
}

export interface SpotifyExportPreview {
  session_id: string;
  files_found: string[];
  library_tracks: {
    total: number;
    matched: number;
    unmatched: number;
    match_rate: number;
  };
  playlists: {
    total: number;
    details: Array<{
      name: string;
      total_tracks: number;
      matched: number;
      match_rate: number;
    }>;
  };
  streaming_history: {
    total_tracks: number;
    matched: number;
    total_streams: number;
  };
}

export interface SpotifyExportDetailedPreview {
  session_id: string;
  summary: SpotifyExportPreview;
  matched_tracks: Array<{
    track: string;
    artist: string;
    album: string;
    local_track_id: string;
    match_method: string;
  }>;
  unmatched_tracks: Array<{
    track: string;
    artist: string;
    album: string;
  }>;
  playlists: Array<{
    name: string;
    total_tracks: number;
    matched: number;
    match_rate: number;
  }>;
}

export interface SpotifyExportImportOptions {
  import_favorites: boolean;
  import_playlists: boolean;
  favorite_matched: boolean;
}

export interface SpotifyExportImportResult {
  favorites_imported: number;
  playlists_created: number;
  tracks_favorited: number;
  errors: string[];
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
    sort_by?: 'added_at';
  }): Promise<UnmatchedTrack[]> => {
    const { data } = await api.get('/spotify/unmatched', { params });
    return data;
  },

  // Spotify data export import
  uploadExport: async (file: File): Promise<SpotifyExportPreview> => {
    const formData = new FormData();
    formData.append('file', file);
    const { data } = await api.post('/spotify/import/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000, // 2 minute timeout for large files
    });
    return data;
  },

  getImportPreview: async (sessionId: string): Promise<SpotifyExportDetailedPreview> => {
    const { data } = await api.get(`/spotify/import/preview/${sessionId}`);
    return data;
  },

  executeImport: async (sessionId: string, options: SpotifyExportImportOptions): Promise<SpotifyExportImportResult> => {
    const { data } = await api.post(`/spotify/import/execute/${sessionId}`, options);
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
