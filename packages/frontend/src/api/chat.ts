import api, { getApiUrl } from './base';

export interface ChatStatusResponse {
  configured: boolean;
  provider: string;
}

export interface ChatHistoryEntry {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export interface ChatStreamRequest {
  message: string;
  history: ChatHistoryEntry[];
  visible_track_ids: string[];
  profile_id?: string | null;
}

export interface ChatQueueTrackPayload {
  id: string;
  title: string;
  artist: string;
  album: string;
}

export interface ChatEphemeralTrackPayload {
  id: string;
  title: string;
  artist: string;
  album: string | null;
  duration_seconds: number | null;
}

export type ChatStreamEvent =
  | { type: 'text'; content: string }
  | { type: 'tool_call'; name: string; input: Record<string, unknown> }
  | { type: 'tool_result'; name: string; result: Record<string, unknown> }
  | { type: 'queue'; tracks: ChatQueueTrackPayload[] }
  | { type: 'playback'; action: string }
  | { type: 'error'; content?: string; message?: string }
  | {
      type: 'ephemeral_playlist_created';
      tracks?: ChatEphemeralTrackPayload[];
      track_ids?: string[];
      name?: string;
      generation_prompt?: string;
    }
  | { type: 'navigate'; view?: string };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string');
}

function parseQueueTracks(value: unknown): ChatQueueTrackPayload[] | null {
  if (!Array.isArray(value)) return null;
  const tracks: ChatQueueTrackPayload[] = [];
  for (const item of value) {
    if (!isRecord(item)) return null;
    if (
      typeof item.id !== 'string' ||
      typeof item.title !== 'string' ||
      typeof item.artist !== 'string' ||
      typeof item.album !== 'string'
    ) {
      return null;
    }
    tracks.push({
      id: item.id,
      title: item.title,
      artist: item.artist,
      album: item.album,
    });
  }
  return tracks;
}

function parseEphemeralTracks(value: unknown): ChatEphemeralTrackPayload[] | null {
  if (!Array.isArray(value)) return null;
  const tracks: ChatEphemeralTrackPayload[] = [];
  for (const item of value) {
    if (!isRecord(item)) return null;
    if (
      typeof item.id !== 'string' ||
      typeof item.title !== 'string' ||
      typeof item.artist !== 'string'
    ) {
      return null;
    }
    const album = item.album;
    const duration = item.duration_seconds;
    if (!(typeof album === 'string' || album === null)) return null;
    if (!(typeof duration === 'number' || duration === null)) return null;
    tracks.push({
      id: item.id,
      title: item.title,
      artist: item.artist,
      album,
      duration_seconds: duration,
    });
  }
  return tracks;
}

export function parseChatStreamEvent(raw: unknown): ChatStreamEvent | null {
  if (!isRecord(raw) || typeof raw.type !== 'string') return null;
  const type = raw.type;

  switch (type) {
    case 'text':
      return typeof raw.content === 'string' ? { type, content: raw.content } : null;
    case 'tool_call':
      return typeof raw.name === 'string' && isRecord(raw.input)
        ? { type, name: raw.name, input: raw.input }
        : null;
    case 'tool_result':
      return typeof raw.name === 'string' && isRecord(raw.result)
        ? { type, name: raw.name, result: raw.result }
        : null;
    case 'queue': {
      const tracks = parseQueueTracks(raw.tracks);
      return tracks ? { type, tracks } : null;
    }
    case 'playback':
      return typeof raw.action === 'string' ? { type, action: raw.action } : null;
    case 'error':
      return {
        type,
        ...(typeof raw.content === 'string' ? { content: raw.content } : {}),
        ...(typeof raw.message === 'string' ? { message: raw.message } : {}),
      };
    case 'ephemeral_playlist_created':
      {
        const tracks = raw.tracks === undefined ? undefined : parseEphemeralTracks(raw.tracks);
        if (raw.tracks !== undefined && tracks === null) return null;
        return {
          type,
          ...(tracks ? { tracks } : {}),
          ...(isStringArray(raw.track_ids) ? { track_ids: raw.track_ids } : {}),
          ...(typeof raw.name === 'string' ? { name: raw.name } : {}),
          ...(typeof raw.generation_prompt === 'string'
            ? { generation_prompt: raw.generation_prompt }
            : {}),
        };
      }
    case 'navigate':
      return {
        type,
        ...(typeof raw.view === 'string' ? { view: raw.view } : {}),
      };
    default:
      return null;
  }
}

async function parseErrorMessage(response: Response): Promise<string> {
  try {
    const data = (await response.json()) as { detail?: string };
    if (typeof data.detail === 'string' && data.detail.length > 0) {
      return data.detail;
    }
  } catch {
    // Fall through to default.
  }
  return `Chat request failed (${response.status})`;
}

export const chatApi = {
  getStatus: async (): Promise<ChatStatusResponse> => {
    const { data } = await api.get('/chat/status');
    return data;
  },

  stream: async (request: ChatStreamRequest, profileId?: string | null): Promise<Response> => {
    const response = await fetch(getApiUrl('/chat/stream'), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(profileId ? { 'X-Profile-ID': profileId } : {}),
      },
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      throw new Error(await parseErrorMessage(response));
    }

    return response;
  },
};
