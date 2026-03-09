import type { LibraryStats } from '../types';
import api from './base';
import { getApiUrl, encodePathSegment } from './base';

export interface ImportResult {
  status: string;
  message: string;
  import_path: string | null;
  files_found: number;
  files: string[];
}

export interface RecentImport {
  name: string;
  path: string;
  file_count: number;
  created_at: string | null;
}

// Unified Sync Types
export type SyncPhase = 'idle' | 'discovering' | 'reading' | 'features' | 'embeddings' | 'melodic' | 'complete' | 'error';

export interface SyncProgress {
  phase: SyncPhase;
  phase_message: string;

  // Discovery/scan metrics
  files_discovered: number;
  files_processed: number;
  files_total: number;
  new_tracks: number;
  updated_tracks: number;
  unchanged_tracks: number;
  relocated_tracks: number;
  marked_missing: number;
  recovered: number;

  // Analysis metrics
  tracks_analyzed: number;
  tracks_pending_analysis: number;
  tracks_total: number;
  analysis_percent: number;

  // Overall
  started_at: string | null;
  current_item: string | null;
  last_heartbeat: string | null;
  errors: string[];
}

export interface SyncStatus {
  status: 'idle' | 'running' | 'completed' | 'error' | 'already_running';
  message: string;
  progress: SyncProgress | null;
}

// Library Browser Types
export interface ArtistSummary {
  name: string;
  track_count: number;
  album_count: number;
  first_track_id: string;
  first_album: string | null;
}

export interface ArtistListResponse {
  items: ArtistSummary[];
  total: number;
  page: number;
  page_size: number;
}

// Artist Detail
export interface ArtistAlbum {
  name: string;
  year: number | null;
  track_count: number;
  first_track_id: string;
}

export interface ArtistTrack {
  id: string;
  title: string | null;
  album: string | null;
  track_number: number | null;
  duration_seconds: number | null;
  year: number | null;
}

export interface ArtistDetailResponse {
  name: string;
  track_count: number;
  album_count: number;
  total_duration_seconds: number;

  // From Last.fm
  bio_summary: string | null;
  bio_content: string | null;
  image_url: string | null;
  lastfm_url: string | null;
  listeners: number | null;
  playcount: number | null;
  tags: string[];
  similar_artists: Array<{
    name: string;
    match_score: number;
    in_library: boolean;
    track_count: number | null;
    image_url: string | null;
    lastfm_url: string | null;
    bandcamp_url: string | null;
  }>;

  // Library content
  albums: ArtistAlbum[];
  tracks: ArtistTrack[];
  first_track_id: string;

  // Cache status
  lastfm_fetched: boolean;
  lastfm_error: string | null;
}

export interface AlbumSummary {
  name: string;
  artist: string;
  year: number | null;
  track_count: number;
  first_track_id: string;
}

export interface AlbumListResponse {
  items: AlbumSummary[];
  total: number;
  page: number;
  page_size: number;
}

export interface AlbumTrack {
  id: string;
  title: string | null;
  track_number: number | null;
  disc_number: number | null;
  duration_seconds: number | null;
}

export interface SimilarAlbumInfo {
  name: string;
  artist: string;
  year: number | null;
  track_count: number;
  first_track_id: string;
  similarity_score: number;
}

export interface DiscoverAlbumInfo {
  name: string;
  artist: string;
  image_url: string | null;
  lastfm_url: string | null;
  bandcamp_url: string | null;
}

export interface AlbumDetailResponse {
  name: string;
  artist: string;
  album_artist: string | null;
  year: number | null;
  genre: string | null;
  track_count: number;
  total_duration_seconds: number;
  first_track_id: string;
  tracks: AlbumTrack[];
  similar_albums: SimilarAlbumInfo[];
  discover_albums: DiscoverAlbumInfo[];
  other_albums_by_artist: SimilarAlbumInfo[];
}

// Year Distribution (for Timeline browser)
export interface YearCount {
  year: number;
  track_count: number;
  album_count: number;
  artist_count: number;
}

export interface YearDistributionResponse {
  years: YearCount[];
  total_with_year: number;
  total_without_year: number;
  min_year: number | null;
  max_year: number | null;
}

// Mood Distribution (for MoodGrid browser)
export interface MoodCell {
  x_min: number;
  x_max: number;
  y_min: number;
  y_max: number;
  track_count: number;
  sample_track_ids: string[];
}

export interface MoodDistributionResponse {
  cells: MoodCell[];
  grid_size: number;
  total_with_mood: number;
  total_without_mood: number;
  x_axis: string;
  y_axis: string;
}

// Music Map (for MusicMap browser)
export interface MapNode {
  id: string;
  name: string;
  x: number;
  y: number;
  track_count: number;
  first_track_id: string;
}

export interface MapEdge {
  source: string;
  target: string;
  weight: number;
}

export interface MusicMapResponse {
  nodes: MapNode[];
  edges: MapEdge[];
  entity_type: string;
  total_entities: number;
}

// Ego-centric Music Map
export interface EgoMapCenter {
  name: string;
  track_count: number;
  first_track_id: string;
}

export interface EgoMapArtist {
  name: string;
  x: number;
  y: number;
  distance: number;
  track_count: number;
  first_track_id: string;
}

export interface EgoMapResponse {
  center: EgoMapCenter;
  artists: EgoMapArtist[];
  mode: string;
  total_artists: number;
}

// 3D Music Map
export interface MapNode3D {
  id: string;
  name: string;
  x: number;
  y: number;
  z: number;
  track_count: number;
  first_track_id: string;
  representative_track_id?: string; // Track closest to artist's audio centroid
}

export interface MusicMap3DResponse {
  nodes: MapNode3D[];
  entity_type: string;
  total_entities: number;
}

// Letter Index (for Alphabet Bar navigation)
export interface LetterIndexResponse {
  letters: Record<string, number>;  // {"A": 0, "B": 47, "C": 123, "#": 500}
  total: number;
}

export const libraryApi = {
  getStats: async (): Promise<LibraryStats> => {
    const { data } = await api.get('/library/stats');
    return data;
  },

  listArtists: async (params?: {
    search?: string;
    sort_by?: 'name' | 'track_count' | 'album_count';
    page?: number;
    page_size?: number;
    has_embeddings?: boolean;
  }): Promise<ArtistListResponse> => {
    const { data } = await api.get('/library/artists', { params });
    return data;
  },

  getArtist: async (
    artistName: string,
    refreshLastfm = false
  ): Promise<ArtistDetailResponse> => {
    const { data } = await api.get(
      `/library/artists/${encodePathSegment(artistName)}`,
      { params: { refresh_lastfm: refreshLastfm } }
    );
    return data;
  },

  listAlbums: async (params?: {
    artist?: string;
    search?: string;
    sort_by?: 'name' | 'year' | 'track_count' | 'artist';
    page?: number;
    page_size?: number;
  }): Promise<AlbumListResponse> => {
    const { data } = await api.get('/library/albums', { params });
    return data;
  },

  getAlbum: async (
    artistName: string,
    albumName: string,
    similarLimit = 8,
    source?: string
  ): Promise<AlbumDetailResponse> => {
    const { data } = await api.get(
      `/library/albums/${encodePathSegment(artistName)}/${encodePathSegment(albumName)}`,
      { params: { similar_limit: similarLimit, ...(source && { source }) } }
    );
    return data;
  },

  getYearDistribution: async (): Promise<YearDistributionResponse> => {
    const { data } = await api.get('/library/years');
    return data;
  },

  getMoodDistribution: async (gridSize = 10, xAxis?: string, yAxis?: string): Promise<MoodDistributionResponse> => {
    const { data } = await api.get('/library/mood-distribution', {
      params: {
        grid_size: gridSize,
        ...(xAxis && { x_axis: xAxis }),
        ...(yAxis && { y_axis: yAxis }),
      },
    });
    return data;
  },

  getMusicMap: async (params?: {
    entity_type?: 'artists' | 'albums';
    limit?: number;
  }): Promise<MusicMapResponse> => {
    const { data } = await api.get('/library/map', { params });
    return data;
  },

  getEgoMap: async (params: {
    center: string;
    limit?: number;
    mode?: 'radial';
  }): Promise<EgoMapResponse> => {
    const { data } = await api.get('/library/map/ego', {
      params: {
        center: params.center,
        limit: params.limit ?? 200,
        mode: params.mode ?? 'radial',
      },
    });
    return data;
  },

  get3DMap: async (params?: {
    entity_type?: 'artists' | 'albums';
  }): Promise<MusicMap3DResponse> => {
    const { data } = await api.get('/library/map/3d', {
      params: {
        entity_type: params?.entity_type ?? 'artists',
      },
    });
    return data;
  },

  sync: async (options: {
    rereadUnchanged?: boolean;
  } = {}): Promise<SyncStatus> => {
    const { data } = await api.post('/library/sync', null, {
      params: {
        reread_unchanged: options.rereadUnchanged ?? false,
      },
    });
    return data;
  },

  getSyncStatus: async (): Promise<SyncStatus> => {
    const { data } = await api.get('/library/sync/status');
    return data;
  },

  cancelSync: async (): Promise<{ status: string; message: string }> => {
    const { data } = await api.post('/library/sync/cancel');
    return data;
  },

  importMusic: async (
    file: File,
    onProgress?: (progress: number) => void
  ): Promise<ImportResult> => {
    const formData = new FormData();
    formData.append('file', file);
    const { data } = await api.post('/library/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (progressEvent) => {
        if (progressEvent.total && onProgress) {
          const percentCompleted = Math.round(
            (progressEvent.loaded * 100) / progressEvent.total
          );
          onProgress(percentCompleted);
        }
      },
    });
    return data;
  },

  getRecentImports: async (limit = 10): Promise<RecentImport[]> => {
    const { data } = await api.get('/library/imports/recent', {
      params: { limit },
    });
    return data;
  },

  getArtistImageUrl: (
    artistName: string,
    size: 'small' | 'medium' | 'large' | 'extralarge' = 'large'
  ): string => {
    // Cache version param to bust browser cache when image sources change
    const cacheVersion = 'v2';
    return getApiUrl(`/library/artists/${encodePathSegment(artistName)}/image?size=${size}&_cv=${cacheVersion}`);
  },

  getLetterIndex: async (params: {
    entity_type: 'tracks' | 'artists' | 'albums';
    sort_field: string;
    search?: string;
    artist?: string;
    album?: string;
  }): Promise<LetterIndexResponse> => {
    const { data } = await api.get('/library/letter-index', { params });
    return data;
  },

  getDiscover: async (params?: {
    recommendations_limit?: number;
  }): Promise<LibraryDiscoverResponse> => {
    const { data } = await api.get('/library/discover', { params });
    return data;
  },
};

// Library Discover types
export interface DiscoverTrack {
  id: string;
  title: string | null;
  artist: string | null;
  album: string | null;
  duration_seconds: number | null;
  play_count: number;
}

export interface DiscoverRecommendedArtist {
  name: string;
  match_score: number;
  in_library: boolean;
  track_count: number | null;
  image_url: string | null;
  lastfm_url: string | null;
  bandcamp_url: string | null;
  based_on_artist: string;
}

export interface LibraryDiscoverResponse {
  unheard_tracks: DiscoverTrack[];
  deep_cuts: DiscoverTrack[];
  recommended_artists: DiscoverRecommendedArtist[];
  recently_added_count: number;
}
