import api, { getApiOrigin } from './base';

export type OutputType = 'browser' | 'sonos' | 'airplay' | 'chromecast' | 'upnp';
export type OutputState = 'idle' | 'playing' | 'paused' | 'buffering' | 'error';

export interface Output {
  id: string;
  name: string;
  type: OutputType;
  state: OutputState;
  volume: number;
  current_track_id: string | null;
  position_ms: number;
}

export interface DiscoverAllResult {
  sonos: Output[];
  upnp: Output[];
  airplay: Output[];
  chromecast: Output[];
}

/**
 * Build an absolute stream URL for a track, suitable for network devices.
 * On web, uses window.location.origin as the backend origin.
 */
export function getAbsoluteStreamUrl(trackId: string): string {
  const origin = getApiOrigin() || (typeof window !== 'undefined' ? window.location.origin : '');
  return `${origin}/api/v1/tracks/${trackId}/stream`;
}

export const outputsApi = {
  list: async (): Promise<Output[]> => {
    const { data } = await api.get<Output[]>('/outputs');
    return data;
  },

  discoverAll: async (): Promise<DiscoverAllResult> => {
    const { data } = await api.get<DiscoverAllResult>('/outputs/discover');
    return data;
  },

  discoverByType: async (type: 'sonos' | 'upnp' | 'airplay' | 'chromecast'): Promise<Output[]> => {
    const { data } = await api.get<Output[]>(`/outputs/discover/${type}`);
    return data;
  },

  getStatus: async (outputId: string): Promise<Output> => {
    const { data } = await api.get<Output>(`/outputs/${outputId}`);
    return data;
  },

  play: async (outputId: string, streamUrl: string, trackId?: string): Promise<void> => {
    await api.post(`/outputs/${outputId}/play`, { stream_url: streamUrl, track_id: trackId });
  },

  pause: async (outputId: string): Promise<void> => {
    await api.post(`/outputs/${outputId}/pause`);
  },

  resume: async (outputId: string): Promise<void> => {
    await api.post(`/outputs/${outputId}/resume`);
  },

  stop: async (outputId: string): Promise<void> => {
    await api.post(`/outputs/${outputId}/stop`);
  },

  seek: async (outputId: string, positionMs: number): Promise<void> => {
    await api.post(`/outputs/${outputId}/seek`, { position_ms: positionMs });
  },

  setVolume: async (outputId: string, volume: number): Promise<void> => {
    await api.post(`/outputs/${outputId}/volume`, { volume });
  },

  delete: async (outputId: string): Promise<void> => {
    await api.delete(`/outputs/${outputId}`);
  },
};
