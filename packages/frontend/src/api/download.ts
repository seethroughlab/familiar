import api from './base';

// Download API (ZIP downloads for playlists and track collections)
function triggerBlobDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export const downloadApi = {
  playlist: async (playlistId: string, name: string): Promise<void> => {
    const response = await api.get(`/download/playlist/${playlistId}`, {
      responseType: 'blob',
      timeout: 300000, // 5 minutes for large playlists
    });
    triggerBlobDownload(response.data, `${name}.zip`);
  },

  smartPlaylist: async (playlistId: string, name: string): Promise<void> => {
    const response = await api.get(`/download/smart-playlist/${playlistId}`, {
      responseType: 'blob',
      timeout: 300000,
    });
    triggerBlobDownload(response.data, `${name}.zip`);
  },

  tracks: async (trackIds: string[], name: string): Promise<void> => {
    const response = await api.post('/download/tracks', { track_ids: trackIds, name }, {
      responseType: 'blob',
      timeout: 300000,
    });
    triggerBlobDownload(response.data, `${name}.zip`);
  },

  analysesZip: async (
    trackIds: string[],
    name: string,
    onProgress?: (completed: number, total: number) => void,
  ): Promise<void> => {
    const response = await api.post(
      '/download/analyses',
      { track_ids: trackIds, name },
      {
        responseType: 'blob',
        timeout: 300000,
        validateStatus: (s: number) => s === 200 || s === 202,
      },
    );

    if (response.status === 200) {
      // Fast path: all analyzed, got ZIP directly
      triggerBlobDownload(response.data, `${name}.zip`);
      return;
    }

    // Slow path: 202 means background analysis started
    // Response is a blob because of responseType, need to parse JSON
    const text = await (response.data as Blob).text();
    const { task_id, needs_analysis } = JSON.parse(text);
    onProgress?.(0, needs_analysis);

    // Poll until ready
    for (;;) {
      await new Promise((r) => setTimeout(r, 2000));
      const statusResp = await api.get(`/download/analyses/${task_id}/status`);
      const { status: taskStatus, completed, total } = statusResp.data;
      onProgress?.(completed, total);
      if (taskStatus === 'ready') break;
      if (taskStatus === 'error') throw new Error('Analysis failed');
    }

    // Download the ZIP
    const zipResponse = await api.get(`/download/analyses/${task_id}/download`, {
      responseType: 'blob',
      timeout: 300000,
    });
    triggerBlobDownload(zipResponse.data, `${name}.zip`);
  },
};
