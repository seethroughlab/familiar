/**
 * Discovery API: new releases (#3) + external albums (per-playlist + listening-profile).
 *
 * Backend surfaces:
 * - `/new-releases/*` — Pass 1
 * - `/external-albums/{id}/dismiss` — generic dismiss (works for any context)
 * - `/library/discover/external-albums` — listening-profile recommendations (Pass 2.5)
 * - `/playlists/{id}/recommendations/external-albums` — per-playlist (used in Pass 4)
 */
import type * as Wire from '@familiar/api-client';
import api from './base';

// ============================================================================
// Shared external-album shape
// ============================================================================

// Response types are the schema's (ADR-0173).
export type ExternalAlbum = Wire.ExternalAlbumResponse;
export type NewReleaseItem = Wire.NewReleaseItem;
export type NewReleasesProgress = Wire.NewReleasesProgress;
export type NewReleasesRotation = Wire.NewReleasesRotation;
export type NewReleasesStatus = Wire.NewReleasesStatus;
export type NewReleasesListResponse = Wire.NewReleasesListResponse;
/** The list endpoint's query parameters, as the schema declares them. */
export type NewReleasesListParams = NonNullable<Wire.NewReleasesListNewReleasesData['query']>;

export const newReleasesApi = {
  async list(params?: NewReleasesListParams): Promise<NewReleasesListResponse> {
    const { data } = await api.get('/new-releases', { params });
    return data;
  },

  async getStatus(): Promise<NewReleasesStatus> {
    const { data } = await api.get('/new-releases/status');
    return data;
  },

  async checkBatch(params?: { batch_size?: number; days_back?: number }): Promise<Wire.CheckStarted> {
    const { data } = await api.post('/new-releases/check/batch', null, { params });
    return data;
  },
};

// ============================================================================
// External albums (generic dismiss + listening-profile + per-playlist)
// ============================================================================

export type ExternalAlbumsResponse = Wire.ExternalAlbumsResponse;

export const externalAlbumsApi = {
  async dismiss(externalAlbumId: string): Promise<void> {
    await api.post(`/external-albums/${externalAlbumId}/dismiss`);
  },

  /** Listening-profile (#2 in Discover) — seeded by user's top-played artists. */
  async listeningProfile(params?: { limit?: number; refresh?: boolean }): Promise<ExternalAlbumsResponse> {
    const { data } = await api.get('/library/discover/external-albums', { params });
    return data;
  },

  /** Per-playlist (#2 in playlist drawer, Pass 4). */
  async forPlaylist(
    playlistId: string,
    params?: { limit?: number; refresh?: boolean },
  ): Promise<ExternalAlbumsResponse> {
    const { data } = await api.get(
      `/playlists/${playlistId}/recommendations/external-albums`,
      { params },
    );
    return data;
  },
};
