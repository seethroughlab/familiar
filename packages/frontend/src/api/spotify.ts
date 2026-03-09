import api from './base';

// ---- Types ----

export interface SpotifyTrack {
  artist: string;
  album: string;
  track: string;
  uri: string;
}

export interface SpotifyPlaylist {
  name: string;
  lastModifiedDate: string;
  track_count: number;
  items: SpotifyTrack[];
}

export interface StreamingStats {
  top_artists: Array<{ artist: string; ms_played: number }>;
  top_tracks: Array<{ artist: string; track: string; ms_played: number }>;
  total_ms: number;
  date_range: { start: string; end: string } | null;
}

export interface MatchResult {
  track_id: string;
  method: string;
  confidence: number;
}

export interface SpotifyImportSummary {
  total_favorites: number;
  matched_favorites: number;
  total_playlists: number;
  total_playlist_tracks: number;
  matched_playlist_tracks: number;
  total_top_tracks: number;
  matched_top_tracks: number;
  total_top_artists: number;
  total_matched: number;
}

export interface SpotifyImportData {
  id: string;
  profile_id: string;
  imported_at: string;
  spotify_username: string | null;
  favorites: SpotifyTrack[];
  playlists: SpotifyPlaylist[];
  streaming_stats: StreamingStats;
  match_results: Record<string, MatchResult>;
  summary: SpotifyImportSummary;
}

// ---- API functions ----

export const spotifyApi = {
  async upload(file: File): Promise<SpotifyImportData> {
    const formData = new FormData();
    formData.append('file', file);
    const { data } = await api.post<SpotifyImportData>('/spotify/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120_000, // 2 min for large ZIPs
    });
    return data;
  },

  async get(): Promise<SpotifyImportData | null> {
    const { data } = await api.get<SpotifyImportData | null>('/spotify/import');
    return data;
  },

  async remove(): Promise<void> {
    await api.delete('/spotify/import');
  },

  async rematch(): Promise<SpotifyImportData> {
    const { data } = await api.post<SpotifyImportData>('/spotify/rematch');
    return data;
  },
};
