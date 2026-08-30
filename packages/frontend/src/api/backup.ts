import api from './base';

// ============================================================================
// Backup/Restore API
// ============================================================================

export interface BackupRequest {
  // Profile data options
  include_play_history?: boolean;
  include_favorites?: boolean;
  include_playlists?: boolean;
  include_smart_playlists?: boolean;
  include_proposed_changes?: boolean;
  // Library data options
  include_library_analysis?: boolean;
  include_embeddings?: boolean;
  include_acoustid?: boolean;
  // Output options
  compress?: boolean;
}

export interface RestorePreviewSummary {
  has_profile_data: boolean;
  has_library_data: boolean;
  profile?: {
    play_history_count: number;
    favorites_count: number;
    playlists_count: number;
    smart_playlists_count: number;
    proposed_changes_count: number;
    user_overrides_count: number;
  };
  library?: {
    total_tracks: number;
    tracks_with_analysis: number;
    tracks_with_embeddings: number;
    tracks_with_user_overrides: number;
    analysis_version: number | null;
  };
}

export interface RestorePreviewMatching {
  total: number;
  matched: number;
  unmatched: number;
  by_method: Record<string, number>;
  unmatched_samples: Array<{
    title: string | null;
    artist: string | null;
    album: string | null;
  }>;
}

export interface RestorePreviewResponse {
  session_id: string;
  summary: RestorePreviewSummary;
  profile_matching: RestorePreviewMatching;
  library_matching: RestorePreviewMatching;
  warnings: string[];
  exported_at: string | null;
  familiar_version: string | null;
  profile_name: string | null;
}

export interface RestoreExecuteRequest {
  session_id: string;
  // Profile import options
  mode: 'merge' | 'overwrite';
  import_play_history?: boolean;
  import_favorites?: boolean;
  import_playlists?: boolean;
  import_smart_playlists?: boolean;
  import_proposed_changes?: boolean;
  import_user_overrides?: boolean;
  // Library import options
  library_mode?: 'match_only' | 'merge' | 'replace';
  apply_analysis?: boolean;
  apply_embeddings?: boolean;
  apply_library_user_overrides?: boolean;
}

/** Per-category outcome of a restore. Defined here since ADR-0077 removed the
 *  export/import wrappers this type used to be declared alongside. */
export interface ImportResultCategory {
  imported: number;
  skipped: number;
  errors: string[];
}

export interface RestoreProfileResults {
  play_history: ImportResultCategory;
  favorites: ImportResultCategory;
  playlists: ImportResultCategory;
  smart_playlists: ImportResultCategory;
  proposed_changes: ImportResultCategory;
  user_overrides: ImportResultCategory;
}

export interface RestoreLibraryResults {
  analysis_imported: number;
  embeddings_imported: number;
  user_overrides_imported: number;
  skipped: number;
  errors: string[];
}

export interface RestoreExecuteResponse {
  status: string;
  results: {
    profile: RestoreProfileResults | null;
    library: RestoreLibraryResults | null;
  };
}

export const backupApi = {
  /**
   * Download a backup as a file.
   * Includes selected profile data and/or library analysis.
   */
  downloadBackup: async (
    request: BackupRequest = {},
    onProgress?: (loaded: number, total: number) => void
  ): Promise<void> => {
    const response = await api.post('/export-import/backup', request, {
      responseType: 'blob',
      timeout: 600000, // 10 minutes for large backups
      onDownloadProgress: (progressEvent) => {
        if (onProgress && progressEvent.total) {
          onProgress(progressEvent.loaded, progressEvent.total);
        }
      },
    });

    // Extract filename from Content-Disposition header or generate one
    const contentDisposition = response.headers['content-disposition'];
    let filename = `familiar-backup-${new Date().toISOString().split('T')[0].replace(/-/g, '')}`;

    if (contentDisposition) {
      const match = contentDisposition.match(/filename="?([^";\n]+)"?/);
      if (match) {
        filename = match[1];
      }
    } else {
      filename += request.compress !== false ? '.json.gz' : '.json';
    }

    // Create blob and trigger download
    const blob = new Blob([response.data], {
      type: request.compress !== false ? 'application/gzip' : 'application/json',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },

  /**
   * Preview a backup file for restore.
   */
  previewRestore: async (
    file: File,
    onProgress?: (loaded: number, total: number) => void
  ): Promise<RestorePreviewResponse> => {
    const formData = new FormData();
    formData.append('file', file);
    const { data } = await api.post('/export-import/restore/preview', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000, // 5 minutes for large files
      onUploadProgress: (progressEvent) => {
        if (onProgress && progressEvent.total) {
          onProgress(progressEvent.loaded, progressEvent.total);
        }
      },
    });
    return data;
  },

  /**
   * Execute a restore from a previewed session.
   */
  executeRestore: async (
    request: RestoreExecuteRequest
  ): Promise<RestoreExecuteResponse> => {
    const { data } = await api.post('/export-import/restore/execute', request, {
      timeout: 600000, // 10 minutes for large restores
    });
    return data;
  },
};
