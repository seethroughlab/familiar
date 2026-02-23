import api from './base';

// Smart Playlists
export interface SmartPlaylistRule {
  field: string;
  operator: string;
  value?: unknown;
}

export interface SmartPlaylist {
  id: string;
  name: string;
  description: string | null;
  rules: SmartPlaylistRule[];
  match_mode: 'all' | 'any';
  order_by: string;
  order_direction: 'asc' | 'desc';
  max_tracks: number | null;
  cached_track_count: number;
  last_refreshed_at: string | null;
  auto_download: boolean;
  created_at: string;
  updated_at: string;
}

export interface SmartPlaylistCreate {
  name: string;
  description?: string;
  rules: SmartPlaylistRule[];
  match_mode?: 'all' | 'any';
  order_by?: string;
  order_direction?: 'asc' | 'desc';
  max_tracks?: number;
}

export interface SmartPlaylistTracksResponse {
  playlist: SmartPlaylist;
  tracks: Array<{
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
  }>;
  total: number;
}

export interface AvailableFields {
  track_fields: Array<{
    name: string;
    type: string;
    description: string;
  }>;
  analysis_fields: Array<{
    name: string;
    type: string;
    description: string;
    range?: [number, number];
  }>;
  play_history_fields?: Array<{
    name: string;
    type: string;
    description: string;
  }>;
  operators: {
    string: string[];
    number: string[];
    date: string[];
    boolean?: string[];
    list: string[];
  };
}

export interface PlaylistImportResult {
  playlist_id: string;
  playlist_name: string;
  total_tracks: number;
  matched_tracks: number;
  unmatched_tracks: number;
  tracks: Array<{
    title: string;
    artist: string;
    matched: boolean;
    matched_track_id: string | null;
    confidence: number;
  }>;
}

export const playlistSharingApi = {
  importPlaylist: async (file: File): Promise<PlaylistImportResult> => {
    const formData = new FormData();
    formData.append('file', file);
    const { data } = await api.post('/playlists/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return data;
  },
};

export const smartPlaylistsApi = {
  list: async (): Promise<SmartPlaylist[]> => {
    const { data } = await api.get('/smart-playlists');
    return data;
  },

  get: async (id: string): Promise<SmartPlaylist> => {
    const { data } = await api.get(`/smart-playlists/${id}`);
    return data;
  },

  create: async (playlist: SmartPlaylistCreate): Promise<SmartPlaylist> => {
    const { data } = await api.post('/smart-playlists', playlist);
    return data;
  },

  update: async (id: string, playlist: Partial<SmartPlaylistCreate> & { auto_download?: boolean }): Promise<SmartPlaylist> => {
    const { data } = await api.put(`/smart-playlists/${id}`, playlist);
    return data;
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/smart-playlists/${id}`);
  },

  getTracks: async (id: string, limit = 100, offset = 0): Promise<SmartPlaylistTracksResponse> => {
    const { data } = await api.get(`/smart-playlists/${id}/tracks`, {
      params: { limit, offset },
    });
    return data;
  },

  refresh: async (id: string): Promise<SmartPlaylist> => {
    const { data } = await api.post(`/smart-playlists/${id}/refresh`);
    return data;
  },

  getAvailableFields: async (): Promise<AvailableFields> => {
    const { data } = await api.get('/smart-playlists/fields/available');
    return data;
  },

  convertToStatic: async (id: string): Promise<{ playlist_id: string; name: string; track_count: number }> => {
    const { data } = await api.post(`/smart-playlists/${id}/convert-to-static`);
    return data;
  },
};

// Playlists API (static playlists with track IDs)
export interface Playlist {
  id: string;
  name: string;
  description: string | null;
  is_auto_generated: boolean;
  is_wishlist: boolean;
  generation_prompt: string | null;
  track_count: number;
  local_track_count: number;
  external_track_count: number;
  auto_download: boolean;
  created_at: string;
  updated_at: string;
}

export interface PlaylistTrack {
  id: string; // track_id or external_track_id
  playlist_track_id: string; // PlaylistTrack.id for reordering/removal
  type: 'local' | 'external';
  title: string | null;
  artist: string | null;
  album: string | null;
  duration_seconds: number | null;
  position: number;

  // Full track fields (local tracks only)
  format?: string | null;
  year?: number | null;
  genre?: string | null;
  track_number?: number | null;
  disc_number?: number | null;
  album_artist?: string | null;
  album_type?: string | null;
  analysis_version?: number | null;

  // External track fields (only present when type === 'external')
  is_matched?: boolean;
  matched_track_id?: string | null;
  match_confidence?: number | null;
  preview_url?: string | null;
  external_links?: Record<string, string>;
}

export interface PlaylistDetail {
  id: string;
  name: string;
  description: string | null;
  is_auto_generated: boolean;
  is_wishlist: boolean;
  generation_prompt: string | null;
  tracks: PlaylistTrack[];
  auto_download: boolean;
  created_at: string;
  updated_at: string;
}

export interface PlaylistCreate {
  name: string;
  description?: string;
  track_ids: string[];
  is_auto_generated?: boolean;
  generation_prompt?: string;
}

export interface RecommendedArtist {
  name: string;
  source: string;
  match_score: number;
  image_url: string | null;
  external_url: string | null;
  local_track_count: number;
}

export interface RecommendedTrack {
  title: string;
  artist: string;
  source: string;
  match_score: number;
  external_url: string | null;
  local_track_id: string | null;
  album: string | null;
}

export interface PlaylistRecommendations {
  artists: RecommendedArtist[];
  tracks: RecommendedTrack[];
  sources_used: string[];
}

export const playlistsApi = {
  list: async (includeAuto = true): Promise<Playlist[]> => {
    const { data } = await api.get('/playlists', {
      params: { include_auto: includeAuto },
    });
    return data;
  },

  get: async (id: string): Promise<PlaylistDetail> => {
    const { data } = await api.get(`/playlists/${id}`);
    return data;
  },

  create: async (playlist: PlaylistCreate): Promise<PlaylistDetail> => {
    const { data } = await api.post('/playlists', playlist);
    return data;
  },

  update: async (id: string, playlist: { name?: string; description?: string; auto_download?: boolean }): Promise<Playlist> => {
    const { data } = await api.put(`/playlists/${id}`, playlist);
    return data;
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/playlists/${id}`);
  },

  addTracks: async (id: string, trackIds: string[]): Promise<PlaylistDetail> => {
    const { data } = await api.post(`/playlists/${id}/tracks`, trackIds);
    return data;
  },

  removeTrack: async (id: string, trackId: string): Promise<void> => {
    await api.delete(`/playlists/${id}/tracks/${trackId}`);
  },

  reorderTracks: async (id: string, trackIds: string[]): Promise<PlaylistDetail> => {
    const { data } = await api.put(`/playlists/${id}/tracks/reorder`, { track_ids: trackIds });
    return data;
  },

  getRecommendations: async (
    id: string,
    params?: { artist_limit?: number; track_limit?: number }
  ): Promise<PlaylistRecommendations> => {
    const { data } = await api.get(`/playlists/${id}/recommendations`, { params });
    return data;
  },

  removeItem: async (playlistId: string, playlistTrackId: string): Promise<void> => {
    await api.delete(`/playlists/${playlistId}/items/${playlistTrackId}`);
  },

  reorderItems: async (id: string, playlistTrackIds: string[]): Promise<PlaylistDetail> => {
    const { data } = await api.put(`/playlists/${id}/tracks/reorder`, {
      playlist_track_ids: playlistTrackIds,
    });
    return data;
  },

  duplicate: async (id: string): Promise<PlaylistDetail> => {
    const { data } = await api.post(`/playlists/${id}/duplicate`);
    return data;
  },

  // Wishlist
  getWishlist: async (): Promise<PlaylistDetail> => {
    const { data } = await api.get('/playlists/wishlist');
    return data;
  },

  addToWishlist: async (request: {
    title: string;
    artist: string;
    album?: string;
    spotify_id?: string;
    preview_url?: string;
    external_data?: Record<string, unknown>;
  }): Promise<PlaylistDetail> => {
    const { data } = await api.post('/playlists/wishlist/add', request);
    return data;
  },
};

// External Tracks API
export interface ExternalTrack {
  id: string;
  title: string;
  artist: string;
  album: string | null;
  duration_seconds: number | null;
  track_number: number | null;
  year: number | null;
  source: string;
  preview_url: string | null;
  preview_source: string | null;
  external_data: Record<string, unknown>;
  is_matched: boolean;
  matched_track_id: string | null;
  matched_at: string | null;
  match_confidence: number | null;
  match_method: string | null;
  spotify_id: string | null;
  isrc: string | null;
  created_at: string;
}

export interface ExternalTrackStats {
  total: number;
  matched: number;
  unmatched: number;
  match_rate: number;
  by_source: Record<string, number>;
}

export interface MatchCandidate {
  track_id: string;
  title: string | null;
  artist: string | null;
  album: string | null;
  duration_seconds: number | null;
  format: string | null;
  year: number | null;
  match_method: string;
  confidence: number;
}

export const externalTracksApi = {
  list: async (params?: {
    matched?: boolean;
    source?: string;
    limit?: number;
    offset?: number;
  }): Promise<ExternalTrack[]> => {
    const { data } = await api.get('/external-tracks', { params });
    return data;
  },

  getStats: async (): Promise<ExternalTrackStats> => {
    const { data } = await api.get('/external-tracks/stats');
    return data;
  },

  get: async (id: string): Promise<ExternalTrack> => {
    const { data } = await api.get(`/external-tracks/${id}`);
    return data;
  },

  create: async (track: {
    title: string;
    artist: string;
    album?: string;
    isrc?: string;
    spotify_id?: string;
    preview_url?: string;
  }): Promise<ExternalTrack> => {
    const { data } = await api.post('/external-tracks', track);
    return data;
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/external-tracks/${id}`);
  },

  manualMatch: async (externalTrackId: string, trackId: string): Promise<ExternalTrack> => {
    const { data } = await api.post(`/external-tracks/${externalTrackId}/match`, {
      track_id: trackId,
    });
    return data;
  },

  removeMatch: async (externalTrackId: string): Promise<ExternalTrack> => {
    const { data } = await api.delete(`/external-tracks/${externalTrackId}/match`);
    return data;
  },

  rematchAll: async (runInBackground = false): Promise<{
    processed: number;
    matched: number;
    task_id?: string;
  }> => {
    const { data } = await api.post('/external-tracks/rematch', null, {
      params: { run_in_background: runInBackground },
    });
    return data;
  },

  resolvePreviewUrl: async (externalTrackId: string): Promise<{ preview_url: string | null; preview_source: string | null }> => {
    const { data } = await api.get(`/external-tracks/${externalTrackId}/preview-url`);
    return data;
  },

  getMatchCandidates: async (externalTrackId: string, limit = 10): Promise<MatchCandidate[]> => {
    const { data } = await api.get(`/external-tracks/${externalTrackId}/match-candidates`, {
      params: { limit },
    });
    return data.candidates;
  },

  matchByAlbum: async (
    sourceAlbum: string,
    targetAlbum: string,
    targetArtist?: string,
  ): Promise<{ matched: number; failed: number; details: Array<{ external_track_id: string; title: string; matched_track_id: string | null; status: string }> }> => {
    const { data } = await api.post('/external-tracks/match-by-album', {
      source_album: sourceAlbum,
      target_album: targetAlbum,
      target_artist: targetArtist,
    });
    return data;
  },
};
