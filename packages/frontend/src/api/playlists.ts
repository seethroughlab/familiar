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
    last_played_at?: string | null;
    play_count?: number | null;
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
  generation_prompt: string | null;
  track_count: number;
  local_track_count: number;
  auto_download: boolean;
  created_at: string;
  updated_at: string;
}

export interface PlaylistTrack {
  id: string; // track_id
  playlist_track_id: string; // PlaylistTrack.id for reordering/removal
  type: 'local';
  title: string | null;
  artist: string | null;
  album: string | null;
  duration_seconds: number | null;
  position: number;

  // Full track fields
  format?: string | null;
  year?: number | null;
  genre?: string | null;
  track_number?: number | null;
  disc_number?: number | null;
  album_artist?: string | null;
  album_type?: string | null;
  analysis_version?: number | null;
  last_played_at?: string | null;
  play_count?: number | null;
}

export interface PlaylistDetail {
  id: string;
  name: string;
  description: string | null;
  is_auto_generated: boolean;
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


/** A structured seed for `POST /playlists/generate` (ADR-0048 point 2). Exactly one shape. */
export interface GeneratePlaylistSeed {
  track_id?: string;
  album?: string;
  artist?: string;
  track_ids?: string[];
  limit?: number;
  max_per_artist?: number;
  include_seed?: boolean;
  name?: string;
}

export interface GeneratedPlaylist {
  playlist_id: string;
  name: string;
  track_count: number;
  seed_track_ids: string[];
  pool_size: number;
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

  /**
   * Generate a playlist from a structured seed (ADR-0048).
   *
   * **No sentence is composed here.** The seed comes from what the listener right-clicked, so there
   * is nothing to interpret — which is what makes this work on a server with no language model.
   */
  generate: async (seed: GeneratePlaylistSeed): Promise<GeneratedPlaylist> => {
    const { data } = await api.post('/playlists/generate', seed);
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

};
