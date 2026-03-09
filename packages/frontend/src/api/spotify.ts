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
  matching_status?: 'pending' | 'complete';
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

export interface UploadResponse extends SpotifyImportData {
  matching_task_id: string;
}

export interface ImportTaskResponse {
  task_id: string;
  status: 'processing';
}

export interface ImportStatusResponse {
  status: 'processing' | 'completed' | 'error';
  message?: string;
  result?: SpotifyImportSummary;
  error?: string;
}

export interface UploadOptions {
  favorites: boolean;
  playlists: boolean;
  streaming: boolean;
}

// ---- API functions ----

export const spotifyApi = {
  async upload(file: File, options: UploadOptions = { favorites: true, playlists: true, streaming: true }): Promise<UploadResponse> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('include_favorites', String(options.favorites));
    formData.append('include_playlists', String(options.playlists));
    formData.append('include_streaming', String(options.streaming));
    const { data } = await api.post<UploadResponse>('/spotify/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return data;
  },

  async pollStatus(taskId: string): Promise<ImportStatusResponse> {
    const { data } = await api.get<ImportStatusResponse>(`/spotify/import/status/${taskId}`);
    return data;
  },

  async get(): Promise<SpotifyImportData | null> {
    const { data } = await api.get<SpotifyImportData | null>('/spotify/import');
    return data;
  },

  async remove(): Promise<void> {
    await api.delete('/spotify/import');
  },

  async rematch(): Promise<ImportTaskResponse> {
    const { data } = await api.post<ImportTaskResponse>('/spotify/rematch');
    return data;
  },
};
