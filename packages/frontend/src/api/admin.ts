import api from './base';

// Health/System Status API
export interface ServiceStatus {
  name: string;
  status: 'healthy' | 'degraded' | 'unhealthy';
  message: string | null;
  details: Record<string, unknown> | null;
}

export interface SystemHealth {
  status: 'healthy' | 'degraded' | 'unhealthy';
  services: ServiceStatus[];
  warnings: string[];
  deployment_mode: 'docker' | 'local';
  version: string;
}

export interface WorkerTask {
  id: string;
  name: string;
  args: unknown[];
  started_at: string | null;
}

export interface WorkerInfo {
  name: string;
  status: string;
  active_tasks: WorkerTask[];
  processed_total: number;
  concurrency: number | null;
}

export interface QueueStats {
  name: string;
  pending: number;
}

export interface TaskFailure {
  task: string;
  error: string;
  track: string | null;
  timestamp: string;
}

export interface WorkerStatus {
  workers: WorkerInfo[];
  queues: QueueStats[];
  analysis_progress: {
    total: number;
    analyzed: number;
    pending: number;
    percent: number;
  };
  recent_failures: TaskFailure[];
}

export const healthApi = {
  getSystemHealth: async (): Promise<SystemHealth> => {
    const { data } = await api.get('/health/system');
    return data;
  },

  getWorkerStatus: async (): Promise<WorkerStatus> => {
    const { data } = await api.get('/health/workers');
    return data;
  },
};

// Diagnostics API
export interface DiagnosticsExport {
  exported_at: string;
  version: string;
  deployment_mode: string;
  system_info: Record<string, unknown>;
  system_health: Record<string, unknown>;
  library_stats: Record<string, unknown>;
  recent_failures: Array<Record<string, unknown>>;
  recent_logs: Array<Record<string, unknown>>;
  settings_summary: Record<string, unknown>;
}

export const diagnosticsApi = {
  export: async (): Promise<DiagnosticsExport> => {
    const { data } = await api.get('/diagnostics/export');
    return data;
  },
};

// Background Jobs API
export interface JobProgress {
  current: number;
  total: number;
}

export interface BackgroundJob {
  type: 'library_sync' | 'artwork_fetch' | 's3_backup';
  status: 'running' | 'idle' | 'error' | 'complete';
  phase: string;
  progress: JobProgress | null;
  message: string;
  current_item: string | null;
  started_at: string | null;
}

export interface BackgroundJobsResponse {
  jobs: BackgroundJob[];
  active_count: number;
}

export const backgroundApi = {
  getJobs: async (): Promise<BackgroundJobsResponse> => {
    const { data } = await api.get('/background/jobs');
    return data;
  },
};

// Update Notifications API
export interface UpdateStatus {
  update_available: boolean;
  current_version: string;
  latest_version: string | null;
  release_url: string | null;
  release_name: string | null;
  published_at: string | null;
  channel: string;
  checked_at: string | null;
  error?: string | null;
}

export const updatesApi = {
  getStatus: async (): Promise<UpdateStatus> => {
    const { data } = await api.get('/updates');
    return data;
  },

  checkNow: async (): Promise<UpdateStatus> => {
    const { data } = await api.post('/updates/check');
    return data;
  },
};
