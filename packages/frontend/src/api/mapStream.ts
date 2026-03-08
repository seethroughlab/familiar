import { getApiUrl } from './base';

export type MapEntityType = 'artists' | 'albums';

export interface MapStreamProgressEvent {
  phase: string;
  progress: number;
  message: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

export const mapStreamApi = {
  fetch2DStream: async (params: {
    entityType: MapEntityType;
    limit?: number;
    signal?: AbortSignal;
  }): Promise<Response> => {
    const response = await fetch(
      getApiUrl(`/library/map/stream?entity_type=${params.entityType}&limit=${params.limit ?? 200}`),
      { signal: params.signal },
    );
    if (!response.ok) {
      throw new Error(`HTTP error: ${response.status}`);
    }
    return response;
  },

  open3DStream: (entityType: MapEntityType = 'artists'): EventSource => {
    return new EventSource(getApiUrl(`/library/map/3d/stream?entity_type=${entityType}`));
  },
};

export function parseMapProgressEvent(raw: unknown): MapStreamProgressEvent | null {
  if (!isRecord(raw)) return null;
  if (
    typeof raw.phase !== 'string' ||
    typeof raw.progress !== 'number' ||
    typeof raw.message !== 'string'
  ) {
    return null;
  }
  return {
    phase: raw.phase,
    progress: raw.progress,
    message: raw.message,
  };
}

export function parseMapErrorMessage(raw: unknown): string | null {
  if (!isRecord(raw)) return null;
  if (typeof raw.error === 'string' && raw.error.length > 0) return raw.error;
  if (typeof raw.message === 'string' && raw.message.length > 0) return raw.message;
  return null;
}
