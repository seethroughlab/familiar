import api from './base';

/** Anthropic-format chat message used in profile export/import/backup. */
export interface ExportChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string | Array<Record<string, unknown>>;
  tool_calls?: Array<Record<string, unknown>>;
  tool_use_id?: string;
}

// Export/Import API
export interface ExportRequest {
  include_play_history?: boolean;
  include_favorites?: boolean;
  include_playlists?: boolean;
  include_smart_playlists?: boolean;
  include_proposed_changes?: boolean;
  chat_history?: ExportChatMessage[];
}

export interface ImportPreviewSummary {
  play_history_count: number;
  favorites_count: number;
  playlists_count: number;
  smart_playlists_count: number;
  proposed_changes_count: number;
  user_overrides_count: number;
  chat_history_count: number;
}

export interface ImportPreviewMatching {
  total: number;
  matched: number;
  unmatched: number;
  /** Keys are matching algorithm names (e.g. "acoustid", "metadata_fuzzy"). */
  by_method: Record<string, number>;
  unmatched_samples: Array<{
    title: string | null;
    artist: string | null;
    album: string | null;
  }>;
}

export interface ImportPreviewResponse {
  session_id: string;
  summary: ImportPreviewSummary;
  matching: ImportPreviewMatching;
  warnings: string[];
  exported_at: string | null;
  familiar_version: string | null;
  profile_name: string | null;
}

export interface ImportExecuteRequest {
  session_id: string;
  mode: 'merge' | 'overwrite';
  import_play_history?: boolean;
  import_favorites?: boolean;
  import_playlists?: boolean;
  import_smart_playlists?: boolean;
  import_proposed_changes?: boolean;
  import_user_overrides?: boolean;
}

export interface ImportResultCategory {
  imported: number;
  skipped: number;
  errors: string[];
}

export interface ImportExecuteResponse {
  status: string;
  results: {
    play_history: ImportResultCategory;
    favorites: ImportResultCategory;
    playlists: ImportResultCategory;
    smart_playlists: ImportResultCategory;
    proposed_changes: ImportResultCategory;
    user_overrides: ImportResultCategory;
    chat_history: ExportChatMessage[];
  };
}

export const exportImportApi = {
  /**
   * Export profile data as JSON.
   * Returns the export data directly (caller should trigger download).
   */
  export: async (request: ExportRequest = {}): Promise<Record<string, unknown>> => {
    const { data } = await api.post('/export-import/export', request);
    return data;
  },

  /**
   * Download export as a file.
   * Creates a blob and triggers download in browser.
   */
  downloadExport: async (request: ExportRequest = {}): Promise<void> => {
    const data = await exportImportApi.export(request);

    // Generate filename
    const date = new Date().toISOString().split('T')[0].replace(/-/g, '');
    const filename = `familiar-export-${date}.json`;

    // Create blob and trigger download
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
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
   * Preview an import file.
   * Returns matching statistics and a session_id for execution.
   */
  previewImport: async (file: File): Promise<ImportPreviewResponse> => {
    const formData = new FormData();
    formData.append('file', file);
    const { data } = await api.post('/export-import/import/preview', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return data;
  },

  /**
   * Execute an import from a previewed session.
   */
  executeImport: async (request: ImportExecuteRequest): Promise<ImportExecuteResponse> => {
    const { data } = await api.post('/export-import/import/execute', request);
    return data;
  },
};

// Library Export/Import API (for machine migration)
export interface LibraryExportRequest {
  include_embeddings?: boolean;
  include_acoustid?: boolean;
  compress?: boolean;
}

export interface LibraryImportPreviewSummary {
  total_tracks: number;
  tracks_with_analysis: number;
  tracks_with_embeddings: number;
  tracks_with_user_overrides: number;
  analysis_version: number | null;
}

export interface LibraryImportPreviewMatching {
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

export interface LibraryImportPreviewResponse {
  session_id: string;
  summary: LibraryImportPreviewSummary;
  matching: LibraryImportPreviewMatching;
  warnings: string[];
  exported_at: string | null;
  familiar_version: string | null;
}

export interface LibraryImportExecuteRequest {
  session_id: string;
  mode: 'match_only' | 'merge' | 'replace';
  apply_metadata?: boolean;
  apply_analysis?: boolean;
  apply_embeddings?: boolean;
  apply_user_overrides?: boolean;
}

export interface LibraryImportResults {
  analysis_imported: number;
  embeddings_imported: number;
  user_overrides_imported: number;
  metadata_updated: number;
  skipped: number;
  errors: string[];
}

export interface LibraryImportExecuteResponse {
  status: string;
  results: LibraryImportResults;
}

export const libraryExportApi = {
  /**
   * Download library export as a file.
   * Includes track metadata, analysis, embeddings, and user overrides.
   */
  downloadExport: async (
    request: LibraryExportRequest = {},
    onProgress?: (loaded: number, total: number) => void
  ): Promise<void> => {
    const response = await api.post('/export-import/library/export', request, {
      responseType: 'blob',
      timeout: 600000, // 10 minutes for large libraries
      onDownloadProgress: (progressEvent) => {
        if (onProgress && progressEvent.total) {
          onProgress(progressEvent.loaded, progressEvent.total);
        }
      },
    });

    // Extract filename from Content-Disposition header or generate one
    const contentDisposition = response.headers['content-disposition'];
    let filename = `familiar-library-export-${new Date().toISOString().split('T')[0].replace(/-/g, '')}`;

    if (contentDisposition) {
      const match = contentDisposition.match(/filename="?([^";\n]+)"?/);
      if (match) {
        filename = match[1];
      }
    } else {
      // Add extension based on compression
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
   * Preview a library import file.
   * Returns matching statistics and a session_id for execution.
   */
  previewImport: async (
    file: File,
    onProgress?: (loaded: number, total: number) => void
  ): Promise<LibraryImportPreviewResponse> => {
    const formData = new FormData();
    formData.append('file', file);
    const { data } = await api.post('/export-import/library/import/preview', formData, {
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
   * Execute a library import from a previewed session.
   */
  executeImport: async (
    request: LibraryImportExecuteRequest
  ): Promise<LibraryImportExecuteResponse> => {
    const { data } = await api.post('/export-import/library/import/execute', request, {
      timeout: 600000, // 10 minutes for large imports
    });
    return data;
  },
};

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
  // Optional chat history
  chat_history?: ExportChatMessage[];
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
    chat_history_count: number;
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

export interface RestoreProfileResults {
  play_history: ImportResultCategory;
  favorites: ImportResultCategory;
  playlists: ImportResultCategory;
  smart_playlists: ImportResultCategory;
  proposed_changes: ImportResultCategory;
  user_overrides: ImportResultCategory;
  chat_history: ExportChatMessage[];
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

// ============================================================================
// S3 Backup API
// ============================================================================

export interface S3ValidateRequest {
  bucket: string;
  region: string;
  prefix?: string;
}

export interface S3ValidateResponse {
  valid: boolean;
  permissions: {
    put: boolean;
    get: boolean;
    list: boolean;
    restore: boolean;
  };
  error: string | null;
}

export interface S3CostEstimate {
  storage_gb: number;
  monthly_cost: number;
  initial_upload_cost: number;
  estimated_restore_cost: number;
  by_category: Record<string, {
    file_count?: number;
    size_bytes: number;
    size_gb: number;
    monthly_cost: number;
  }>;
}

export interface S3BackupStatus {
  enabled: boolean;
  bucket: string | null;
  region: string | null;
  schedule: string | null;
  is_running: boolean;
  last_backup: {
    timestamp: string;
    duration_seconds: number;
    files_uploaded: number;
    files_skipped: number;
    bytes_uploaded: number;
    status: string;
    error?: string;
  } | null;
  progress: S3BackupProgress | null;
}

export interface S3BackupProgress {
  status: string;
  phase: string;
  files_total: number;
  files_uploaded: number;
  files_skipped: number;
  bytes_uploaded: number;
  current_file: string | null;
  started_at: string | null;
  error: string | null;
}

export interface S3ManifestSummary {
  last_backup_at: string | null;
  database: { s3_key: string; size_bytes: number; checksum: string } | null;
  settings: { s3_key: string; size_bytes: number } | null;
  file_count: number;
  total_size_bytes: number;
  by_category: Record<string, { count: number; size_bytes: number }>;
}

export interface S3RestoreState {
  status: 'none' | 'retrieving' | 'available' | 'downloading' | 'complete' | 'error';
  initiated_at?: string;
  total_files?: number;
  files_requested?: number;
  files_available?: number;
  errors?: number;
  categories?: string[];
  completed_at?: string;
}

export interface S3BackupHistoryEntry {
  timestamp: string;
  duration_seconds: number;
  files_uploaded: number;
  files_skipped: number;
  bytes_uploaded: number;
  status: string;
  error?: string;
}

export const s3BackupApi = {
  validate: async (request: S3ValidateRequest): Promise<S3ValidateResponse> => {
    const { data } = await api.post('/s3-backup/validate', request);
    return data;
  },

  getEstimate: async (): Promise<S3CostEstimate> => {
    const { data } = await api.get('/s3-backup/estimate');
    return data;
  },

  getStatus: async (): Promise<S3BackupStatus> => {
    const { data } = await api.get('/s3-backup/status');
    return data;
  },

  runBackup: async (): Promise<{ status: string; message: string }> => {
    const { data } = await api.post('/s3-backup/run');
    return data;
  },

  getProgress: async (): Promise<S3BackupProgress> => {
    const { data } = await api.get('/s3-backup/progress');
    return data;
  },

  cancelBackup: async (): Promise<{ status: string; message: string }> => {
    const { data } = await api.post('/s3-backup/cancel');
    return data;
  },

  getHistory: async (): Promise<S3BackupHistoryEntry[]> => {
    const { data } = await api.get('/s3-backup/history');
    return data;
  },

  getManifest: async (): Promise<S3ManifestSummary> => {
    const { data } = await api.get('/s3-backup/manifest');
    return data;
  },

  initiateRestore: async (categories?: string[]): Promise<S3RestoreState> => {
    const { data } = await api.post('/s3-backup/restore', { categories });
    return data;
  },

  getRestoreStatus: async (): Promise<S3RestoreState> => {
    const { data } = await api.get('/s3-backup/restore/status');
    return data;
  },

  checkRestoreAvailability: async (): Promise<S3RestoreState> => {
    const { data } = await api.post('/s3-backup/restore/check');
    return data;
  },

  downloadAndRestore: async (confirm: boolean): Promise<{ status: string; message: string }> => {
    const { data } = await api.post('/s3-backup/restore/download', { confirm });
    return data;
  },

  getRestoreProgress: async (): Promise<S3BackupProgress> => {
    const { data } = await api.get('/s3-backup/restore/progress');
    return data;
  },
};
