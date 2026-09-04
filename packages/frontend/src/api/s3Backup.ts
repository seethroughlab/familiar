import api from './base';

/**
 * S3 Glacier Deep Archive backup.
 *
 * The endpoints existed for months with no caller in either client — backups ran
 * on a scheduler nothing could enable, and the restore path had never been
 * executed by anything. These are the wrappers that make both reachable.
 *
 * Credentials are deliberately absent: bucket, region, prefix and keys come from
 * the environment and are read-only in `/settings`. Only `s3_backup_enabled` and
 * `s3_backup_schedule` are writable, so this client never handles a secret.
 */

export interface BackupStatus {
  enabled: boolean;
  bucket: string | null;
  region: string | null;
  schedule: string | null;
  is_running: boolean;
  last_backup: Record<string, unknown> | null;
  progress: BackupProgress | null;
}

export interface BackupProgress {
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

export interface BackupValidation {
  valid: boolean;
  permissions: Record<string, boolean>;
  error: string | null;
}

export interface BackupCostEstimate {
  storage_gb: number;
  monthly_cost: number;
  initial_upload_cost: number;
  estimated_restore_cost: number;
  by_category: Record<string, { file_count?: number; size_gb?: number; monthly_cost?: number }>;
}

export interface BackupManifest {
  last_backup_at: string | null;
  database: Record<string, unknown> | null;
  settings: Record<string, unknown> | null;
  file_count: number;
  total_size_bytes: number;
  by_category: Record<string, unknown>;
}

export interface RestoreThawResult {
  categories?: string[];
  files_requested?: number;
  files_available?: number;
  errors?: number;
  status?: string;
  error?: string;
}

export const s3BackupApi = {
  getStatus: async (): Promise<BackupStatus> => {
    const { data } = await api.get('/s3-backup/status');
    return data;
  },

  getProgress: async (): Promise<BackupProgress> => {
    const { data } = await api.get('/s3-backup/progress');
    return data;
  },

  getHistory: async (): Promise<Record<string, unknown>[]> => {
    const { data } = await api.get('/s3-backup/history');
    return data;
  },

  getManifest: async (): Promise<BackupManifest> => {
    const { data } = await api.get('/s3-backup/manifest');
    return data;
  },

  getEstimate: async (): Promise<BackupCostEstimate> => {
    const { data } = await api.get('/s3-backup/estimate');
    return data;
  },

  validate: async (params: {
    bucket: string;
    region?: string;
    prefix?: string;
  }): Promise<BackupValidation> => {
    const { data } = await api.post('/s3-backup/validate', params);
    return data;
  },

  run: async (): Promise<{ status: string; message?: string }> => {
    const { data } = await api.post('/s3-backup/run');
    return data;
  },

  cancel: async (): Promise<{ status: string }> => {
    const { data } = await api.post('/s3-backup/cancel');
    return data;
  },

  // ── Restore, in the three phases Glacier forces ──────────────────────────
  //
  // Deep Archive cannot be read directly, so a restore is: ask for a thaw, wait
  // 12-48 hours, then download. `download` takes a safety dump of the current
  // database before overwriting it, and aborts if that dump fails.

  initiateRestore: async (categories?: string[]): Promise<RestoreThawResult> => {
    const { data } = await api.post('/s3-backup/restore', { categories: categories ?? null });
    return data;
  },

  checkRestore: async (): Promise<Record<string, unknown>> => {
    const { data } = await api.post('/s3-backup/restore/check');
    return data;
  },

  getRestoreStatus: async (): Promise<Record<string, unknown>> => {
    const { data } = await api.get('/s3-backup/restore/status');
    return data;
  },

  getRestoreProgress: async (): Promise<BackupProgress> => {
    const { data } = await api.get('/s3-backup/restore/progress');
    return data;
  },

  /** Destructive: overwrites the live database. Requires confirm=true server-side. */
  downloadAndRestore: async (): Promise<{ status: string; message?: string; error?: string }> => {
    const { data } = await api.post('/s3-backup/restore/download', { confirm: true });
    return data;
  },
};
