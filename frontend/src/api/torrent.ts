import api from './base';

export interface TorrentResult {
  title: string;
  indexer: string;
  size_bytes: number;
  size_display: string;
  seeders: number;
  leechers: number;
  magnet_url: string | null;
  torrent_url: string | null;
  info_url: string | null;
  category: string; // "lossless" | "mp3" | "audio"
  publish_date: string | null;
}

export interface TorrentSearchResponse {
  results: TorrentResult[];
  total: number;
  query: string;
  error: string | null;
}

export interface TorrentConnectionStatus {
  ok: boolean;
  provider: string;
  error: string | null;
}

export interface DownloadResponse {
  ok: boolean;
  name: string | null;
  duplicate: boolean;
  error: string | null;
}

export const torrentSearchApi = {
  search: async (params: {
    artist: string;
    title?: string;
    album?: string;
    limit?: number;
  }): Promise<TorrentSearchResponse> => {
    const { data } = await api.get('/torrent-search/search', { params });
    return data;
  },

  getStatus: async (): Promise<TorrentConnectionStatus> => {
    const { data } = await api.get('/torrent-search/status');
    return data;
  },

  testConnection: async (): Promise<TorrentConnectionStatus> => {
    const { data } = await api.post('/torrent-search/test');
    return data;
  },

  download: async (url: string): Promise<DownloadResponse> => {
    const { data } = await api.post('/torrent-search/download', { url });
    return data;
  },
};
