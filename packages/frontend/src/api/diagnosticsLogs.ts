import api from './base';

export interface FrontendLogEntryPayload {
  level: string;
  namespace: string;
  message: string;
  timestamp: string;
  context: Record<string, unknown> | undefined;
}

export interface FrontendLogEntry {
  id: string;
  level: string;
  namespace: string;
  message: string;
  client_ts: string | null;
  server_ts: string | null;
  context: Record<string, unknown> | null;
}

export interface ListFrontendLogsResponse {
  entries: FrontendLogEntry[];
  total: number;
}

export const frontendLogsApi = {
  ingest: async (entries: FrontendLogEntryPayload[]): Promise<void> => {
    await api.post('/diagnostics/frontend-logs', { entries });
  },

  list: async (params: {
    level?: string;
    namespace?: string;
    limit?: number;
  }): Promise<ListFrontendLogsResponse> => {
    const { data } = await api.get('/diagnostics/frontend-logs', { params });
    return data;
  },

  clear: async (): Promise<void> => {
    await api.delete('/diagnostics/frontend-logs');
  },
};
