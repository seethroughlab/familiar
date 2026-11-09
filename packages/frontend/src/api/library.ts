import type * as Wire from '@familiar/api-client';
import type { LibraryStats } from '../types';
import api from './base';
import { getApiUrl, encodePathSegment } from './base';

// Response types are the schema's (ADR-0173). The names are kept so callers need not change; each
// is the generated type, and `pnpm generate:api` is what updates them.
/**
 * Sync progress as the UI reads it: every field present.
 *
 * The server always sends all of them (each has a default in `SyncProgress`), but a default makes a
 * field optional in the schema, and `dump_openapi.py` turns `progress: SyncProgress | None` into an
 * optional property, so the generated type says "maybe absent" where the wire says "present, or
 * null". The schema cannot simply be tightened: familiar-apple generates `SyncStatus` too, and its
 * optionals would change under `LibrarySyncStore`. So the adapter fills the defaults once, here.
 */
export type SyncProgress = Required<Wire.SyncProgress>;
export type SyncPhase = SyncProgress['phase'];
export type SyncStatus = Omit<Wire.SyncStatus, 'progress'> & { progress: SyncProgress | null };

const PROGRESS_DEFAULTS: SyncProgress = {
  phase: 'idle',
  phase_message: '',
  files_discovered: 0,
  files_processed: 0,
  files_total: 0,
  new_tracks: 0,
  updated_tracks: 0,
  unchanged_tracks: 0,
  relocated_tracks: 0,
  marked_missing: 0,
  recovered: 0,
  tracks_analyzed: 0,
  tracks_pending_analysis: 0,
  tracks_total: 0,
  analysis_percent: 0,
  started_at: null,
  current_item: null,
  last_heartbeat: null,
  errors: [],
};

/** A sync status off the wire, with progress either complete or null. */
export function toSyncStatus(wire: Wire.SyncStatus): SyncStatus {
  return { ...wire, progress: wire.progress ? { ...PROGRESS_DEFAULTS, ...wire.progress } : null };
}

export type ArtistSummary = Wire.ArtistSummary;
export type ArtistListResponse = Wire.ArtistListResponse;
export type ArtistAlbum = Wire.ArtistAlbum;
export type ArtistTrack = Wire.ArtistTrack;
export type ArtistDetailResponse = Wire.ArtistDetailResponse;

export type AlbumSummary = Wire.AlbumSummary;
export type AlbumListResponse = Wire.AlbumListResponse;
export type AlbumTrack = Wire.AlbumTrack;
export type SimilarAlbumInfo = Wire.SimilarAlbumInfo;
export type DiscoverAlbumInfo = Wire.DiscoverAlbumInfo;
export type AlbumDetailResponse = Wire.AlbumDetailResponse;

export type YearCount = Wire.YearCount;
export type YearDistributionResponse = Wire.YearDistributionResponse;
export type MoodCell = Wire.MoodCell;
export type MoodDistributionResponse = Wire.MoodDistributionResponse;

export type MapNode = Wire.MapNode;
export type MapEdge = Wire.MapEdge;
export type MusicMapResponse = Wire.MusicMapResponse;
export type EgoMapCenter = Wire.EgoMapCenterResponse;
export type EgoMapArtist = Wire.EgoMapArtistResponse;
export type EgoMapResponse = Wire.EgoMapResponse;
export type MapNode3D = Wire.MapNode3dResponse;
export type MusicMap3DResponse = Wire.MusicMap3dResponse;
export type LetterIndexResponse = Wire.LetterIndexResponse;

/** Duplicate groups from a whole-library scan. Preview only — the server has no apply route. */
export type DuplicateTrackInfo = Wire.TrackInfo;
export type DuplicateGroup = Wire.DuplicateGroup;
export type DeduplicatePreview = Wire.DeduplicatePreviewResponse;
export type ArtworkCoverage = Wire.ArtworkCoverageResponse;

export type DiscoverTrack = Wire.DiscoverTrack;
export type DiscoverRecommendedArtist = Wire.DiscoverRecommendedArtist;
export type LibraryDiscoverResponse = Wire.DiscoverResponse;

export const libraryApi = {
  getStats: async (): Promise<LibraryStats> => {
    const { data } = await api.get('/library/stats');
    return data;
  },

  /**
   * Ask the internet again for every album showing a placeholder.
   *
   * Explicit, never automatic: it queues hundreds of external lookups. The server applies the same
   * 30-day rule the per-album path uses, so pressing this twice in a day does nothing the second
   * time — the button cannot bypass the rate limit.
   */
  refetchGeneratedArtwork: async (): Promise<Wire.RefetchGeneratedResponse> => {
    const { data } = await api.post('/artwork/refetch-generated');
    return data;
  },

  getArtworkCoverage: async (): Promise<ArtworkCoverage> => {
    const { data } = await api.get('/artwork/coverage');
    return data;
  },

  /**
   * Find duplicate tracks. **A POST that scans the whole library**, so it is never called on
   * page load — ADR-0058 phase 4 puts it behind an explicit button for that reason.
   */
  deduplicatePreview: async (params?: {
    search?: string;
    artist?: string;
    album?: string;
  }): Promise<DeduplicatePreview> => {
    const { data } = await api.post('/library/deduplicate/preview', null, { params });
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
    return toSyncStatus(data);
  },

  getSyncStatus: async (): Promise<SyncStatus> => {
    const { data } = await api.get('/library/sync/status');
    return toSyncStatus(data);
  },

  cancelSync: async (): Promise<Wire.CancelResponse> => {
    const { data } = await api.post('/library/sync/cancel');
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
    seed_artists?: number;
    similar_per_artist?: number;
    min_match_score?: number;
  }): Promise<LibraryDiscoverResponse> => {
    const { data } = await api.get('/library/discover', { params });
    return data;
  },
};
