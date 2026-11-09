import type * as Wire from '@familiar/api-client';
import api from './base';

// Smart Playlists
export type SmartPlaylistRule = Wire.RuleSchema;

export type SmartPlaylist = Wire.SmartPlaylistResponse;

export type SmartPlaylistCreate = Wire.SmartPlaylistCreate;

export type SmartPlaylistTracksResponse = Wire.SmartPlaylistTracksResponse;

export type AvailableFields = Wire.AvailableFieldsResponse;

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
export type Playlist = Wire.PlaylistResponse;

export type PlaylistTrack = Wire.TrackInPlaylist;

export type PlaylistDetail = Wire.PlaylistDetailResponse;

export type PlaylistCreate = Wire.PlaylistCreate;

export type RecommendedArtist = Wire.RecommendedArtistResponse;

export type RecommendedTrack = Wire.RecommendedTrackResponse;

export type PlaylistRecommendations = Wire.RecommendationsResponse;


/** A structured seed for `POST /playlists/generate` (ADR-0048 point 2). Exactly one shape. */
export type GeneratePlaylistSeed = Wire.GeneratePlaylistRequest;

export type GeneratedPlaylist = Wire.GeneratePlaylistResponse;

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
