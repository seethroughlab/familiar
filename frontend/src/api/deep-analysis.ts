import api from './base';

export interface DeepAnalysisStatus {
  status: 'ready' | 'processing' | 'cached';
  track_id: string;
}

export interface DeepAnalysisResult {
  track_id: string;
  version: number;
  results: Record<string, unknown>;
  midi_path: string | null;
  section_errors: Array<{ section: string; error: string }>;
  analysis_duration_seconds: number | null;
  created_at: string | null;
}

export interface BulkAnalysisStatus {
  status: 'processing' | 'completed';
  completed: number;
  total: number;
  track_ids: string[];
  errors: Array<{ track_id: string; error: string }>;
}

export const deepAnalysisApi = {
  trigger: (trackId: string) =>
    api.post<DeepAnalysisStatus>(`/tracks/${trackId}/deep-analysis`),

  getStatus: (trackId: string) =>
    api.get<DeepAnalysisResult>(`/tracks/${trackId}/deep-analysis`),

  downloadReport: async (trackId: string): Promise<void> => {
    const response = await api.get(`/tracks/${trackId}/deep-analysis/report`, {
      responseType: 'blob',
    });
    const blob = new Blob([response.data], { type: 'text/markdown' });
    const disposition = response.headers['content-disposition'];
    let filename = 'track-analysis.md';
    if (disposition) {
      const match = disposition.match(/filename="?(.+?)"?$/);
      if (match) filename = match[1];
    }
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },

  downloadMidi: async (trackId: string): Promise<void> => {
    const response = await api.get(`/tracks/${trackId}/deep-analysis/midi`, {
      responseType: 'blob',
    });
    const blob = new Blob([response.data], { type: 'audio/midi' });
    const disposition = response.headers['content-disposition'];
    let filename = 'transcription.mid';
    if (disposition) {
      const match = disposition.match(/filename="?(.+?)"?$/);
      if (match) filename = match[1];
    }
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },

  triggerBulk: (trackIds: string[]) =>
    api.post<{ status: string; task_id: string; total: number }>(
      '/tracks/deep-analysis/bulk',
      { track_ids: trackIds }
    ),

  getBulkStatus: (taskId: string) =>
    api.get<BulkAnalysisStatus>(`/tracks/deep-analysis/bulk/${taskId}`),

  downloadBulkReport: async (taskId: string): Promise<void> => {
    const response = await api.get(
      `/tracks/deep-analysis/bulk/${taskId}/report`,
      { responseType: 'blob' }
    );
    const blob = new Blob([response.data], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'track-analysis.md';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },
};
