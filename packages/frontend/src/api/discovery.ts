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
// What's new for this profile (ADR-0179)
// ============================================================================

export type WhatsNew = Wire.WhatsNewResponse;

export const whatsNewApi = {
  async get(params?: { limit?: number }): Promise<WhatsNew> {
    const { data } = await api.get('/library/discover/whats-new', { params });
    return data;
  },

  /**
   * Record that this profile has seen what was found up to `through`: the newest `discovered_at`
   * the page actually showed, passed back exactly as the server wrote it, never the current time.
   */
  async markSeen(through: string): Promise<void> {
    await api.post('/library/discover/whats-new/seen', { through });
  },
};

/** The newest `discovered_at` among rows, as the server's own string, or null. */
export function newestDiscoveredAt(rows: readonly { discovered_at: string }[]): string | null {
  let newest: string | null = null;
  for (const row of rows) {
    // Compared as instants: the server's ISO strings drop zero microseconds, so they do not sort
    // as text.
    if (newest === null || Date.parse(row.discovered_at) > Date.parse(newest)) {
      newest = row.discovered_at;
    }
  }
  return newest;
}

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
