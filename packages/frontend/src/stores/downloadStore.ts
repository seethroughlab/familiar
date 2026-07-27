/**
 * Global download queue store for managing offline downloads across navigation.
 * Downloads persist to IndexedDB and can resume after app restart (iOS resilience).
 */
import { create } from 'zustand';
import * as offlineService from '../services/offlineService';
import { db, type PersistedDownloadJob } from '../db';
import { showSuccess, showError, showWarning } from './toastStore';
import { createLogger } from '../utils/logger';

const log = createLogger('Download');

export type DownloadJobStatus = 'queued' | 'downloading' | 'completed' | 'failed' | 'cancelled';

export interface DownloadJob {
  id: string;                    // Unique job ID (e.g., "playlist-123", "album-artist-albumname")
  type: 'playlist' | 'smart-playlist' | 'album';
  name: string;                  // Display name
  trackIds: string[];            // All track IDs to download
  completedIds: string[];        // Successfully downloaded
  failedIds: string[];           // Failed downloads
  currentTrackId: string | null; // Currently downloading
  currentProgress: number;       // 0-100 for current track
  status: DownloadJobStatus;
  startedAt: Date;
  error?: string;
  // Deliberately slowed to leave bandwidth for playback (see services/playbackGate).
  // Surfaced so a throttled download doesn't look like a stalled one.
  throttled?: boolean;
}

interface DownloadState {
  jobs: Map<string, DownloadJob>;
  activeJobId: string | null;

  // Actions
  startDownload: (
    id: string,
    type: DownloadJob['type'],
    name: string,
    trackIds: string[]
  ) => void;
  cancelDownload: (id: string) => void;
  getJob: (id: string) => DownloadJob | undefined;
  getActiveJob: () => DownloadJob | undefined;
  clearCompletedJobs: () => void;
}

// Track the current abort controller for cancellation
let currentAbortController: AbortController | null = null;

// Flag to track if we've restored from IndexedDB
let hasRestoredFromDB = false;

// Track if we've shown storage full error (avoid spam)
let hasShownStorageFullError = false;

// Listen for storage-full events from offlineService
if (typeof window !== 'undefined') {
  window.addEventListener('offline-storage-full', () => {
    if (!hasShownStorageFullError) {
      hasShownStorageFullError = true;
      showError('Storage full', {
        description: 'Free up space by removing downloaded tracks in Settings > Downloads.',
        duration: 10000, // Show longer since this is important
      });
      // Reset flag after a minute to allow showing again if user tries again
      setTimeout(() => {
        hasShownStorageFullError = false;
      }, 60000);
    }
  });
}

// Throttled progress update to reduce state updates (max 2/second)
let lastProgressUpdate = 0;
let pendingProgressUpdate: { jobId: string; progress: number } | null = null;
let progressUpdateTimeout: ReturnType<typeof setTimeout> | null = null;
const PROGRESS_UPDATE_INTERVAL = 500; // 500ms = max 2 updates/second

function throttledProgressUpdate(jobId: string, progress: number) {
  const now = Date.now();
  const timeSinceLastUpdate = now - lastProgressUpdate;

  if (timeSinceLastUpdate >= PROGRESS_UPDATE_INTERVAL) {
    // Enough time has passed, update immediately
    lastProgressUpdate = now;
    updateJob(jobId, { currentProgress: progress });
  } else {
    // Store pending update and schedule it
    pendingProgressUpdate = { jobId, progress };
    if (!progressUpdateTimeout) {
      progressUpdateTimeout = setTimeout(() => {
        if (pendingProgressUpdate) {
          lastProgressUpdate = Date.now();
          updateJob(pendingProgressUpdate.jobId, { currentProgress: pendingProgressUpdate.progress });
          pendingProgressUpdate = null;
        }
        progressUpdateTimeout = null;
      }, PROGRESS_UPDATE_INTERVAL - timeSinceLastUpdate);
    }
  }
}

/**
 * Persist a job to IndexedDB.
 */
async function persistJob(job: DownloadJob): Promise<void> {
  const persisted: PersistedDownloadJob = {
    id: job.id,
    type: job.type,
    name: job.name,
    trackIds: job.trackIds,
    completedIds: job.completedIds,
    failedIds: job.failedIds,
    status: job.status === 'cancelled' ? 'paused' : job.status,
    startedAt: job.startedAt,
    updatedAt: new Date(),
  };
  await db.downloadQueue.put(persisted);
}

/**
 * Remove a job from IndexedDB.
 */
async function removePersistedJob(id: string): Promise<void> {
  await db.downloadQueue.delete(id);
}

/**
 * Restore download queue from IndexedDB on app start.
 * Called automatically when the store is first accessed.
 */
export async function restoreDownloadQueue(): Promise<void> {
  if (hasRestoredFromDB) return;
  hasRestoredFromDB = true;

  try {
    const persistedJobs = await db.downloadQueue.toArray();

    if (persistedJobs.length === 0) return;

    log.info('Restoring', persistedJobs.length, 'jobs from IndexedDB');

    const jobs = new Map<string, DownloadJob>();

    for (const persisted of persistedJobs) {
      // Skip completed/failed jobs older than 1 hour
      if (
        (persisted.status === 'completed' || persisted.status === 'failed') &&
        Date.now() - persisted.updatedAt.getTime() > 60 * 60 * 1000
      ) {
        await removePersistedJob(persisted.id);
        continue;
      }

      // Convert downloading/paused jobs back to queued for retry
      const status: DownloadJobStatus =
        persisted.status === 'downloading' || persisted.status === 'paused'
          ? 'queued'
          : persisted.status;

      const job: DownloadJob = {
        id: persisted.id,
        type: persisted.type,
        name: persisted.name,
        trackIds: persisted.trackIds,
        completedIds: persisted.completedIds,
        failedIds: persisted.failedIds,
        currentTrackId: null,
        currentProgress: 0,
        status,
        startedAt: persisted.startedAt,
      };

      jobs.set(job.id, job);
    }

    if (jobs.size > 0) {
      useDownloadStore.setState({ jobs });
      log.info('Restored', jobs.size, 'jobs, starting queue processing');
      // Auto-resume downloads
      processNextJob();
    }
  } catch (error) {
    log.error('Failed to restore queue from IndexedDB:', error);
  }
}

export const useDownloadStore = create<DownloadState>((set, get) => ({
  jobs: new Map(),
  activeJobId: null,

  startDownload: (id, type, name, trackIds) => {
    const state = get();

    log.info('startDownload called:', id, 'with', trackIds.length, 'tracks');

    // If this job already exists and is downloading, don't start another
    const existingJob = state.jobs.get(id);
    if (existingJob && (existingJob.status === 'downloading' || existingJob.status === 'queued')) {
      log.info('Job already in progress, skipping');
      return;
    }

    // Filter out already-downloaded tracks (will be checked async)
    const job: DownloadJob = {
      id,
      type,
      name,
      trackIds,
      completedIds: [],
      failedIds: [],
      currentTrackId: null,
      currentProgress: 0,
      status: 'queued',
      startedAt: new Date(),
    };

    // Add job to queue
    const newJobs = new Map(state.jobs);
    newJobs.set(id, job);
    set({ jobs: newJobs });

    // Persist to IndexedDB for iOS resilience
    persistJob(job).catch((err) =>
      log.error('Failed to persist new job:', err)
    );

    // If no active job, start processing
    if (!state.activeJobId) {
      processNextJob();
    }
  },

  cancelDownload: (id) => {
    const state = get();
    const job = state.jobs.get(id);
    if (!job) return;

    // If this is the active job, abort it
    if (state.activeJobId === id && currentAbortController) {
      currentAbortController.abort();
      currentAbortController = null;
    }

    // Update job status
    const newJobs = new Map(state.jobs);
    newJobs.set(id, { ...job, status: 'cancelled' });
    set({
      jobs: newJobs,
      activeJobId: state.activeJobId === id ? null : state.activeJobId,
    });

    // Remove cancelled job after a brief delay
    setTimeout(async () => {
      const currentState = get();
      const currentJobs = new Map(currentState.jobs);
      currentJobs.delete(id);
      set({ jobs: currentJobs });

      // Also remove from IndexedDB
      await removePersistedJob(id).catch((err) =>
        log.error('Failed to remove cancelled job:', err)
      );
    }, 2000);

    // Process next job if this was the active one
    if (state.activeJobId === id) {
      processNextJob();
    }
  },

  getJob: (id) => get().jobs.get(id),

  getActiveJob: () => {
    const state = get();
    return state.activeJobId ? state.jobs.get(state.activeJobId) : undefined;
  },

  clearCompletedJobs: () => {
    const state = get();
    const newJobs = new Map(state.jobs);
    for (const [id, job] of newJobs) {
      if (job.status === 'completed' || job.status === 'failed' || job.status === 'cancelled') {
        newJobs.delete(id);
      }
    }
    set({ jobs: newJobs });
  },
}));

// Process the next queued job
async function processNextJob() {
  const state = useDownloadStore.getState();

  // Find next queued job
  let nextJob: DownloadJob | undefined;
  for (const job of state.jobs.values()) {
    if (job.status === 'queued') {
      nextJob = job;
      break;
    }
  }

  if (!nextJob) {
    useDownloadStore.setState({ activeJobId: null });
    return;
  }

  log.info('Starting job:', nextJob.id, 'with', nextJob.trackIds.length, 'tracks');

  // Set as active
  useDownloadStore.setState({ activeJobId: nextJob.id });

  // Get already-downloaded track IDs
  const offlineIds = new Set(await offlineService.getOfflineTrackIds());
  const tracksToDownload = nextJob.trackIds.filter(id => !offlineIds.has(id));

  log.info('Already offline:', offlineIds.size, 'To download:', tracksToDownload.length);

  // If all tracks already downloaded, mark as complete
  if (tracksToDownload.length === 0) {
    log.info('All tracks already offline, marking job as complete');
    updateJob(nextJob.id, {
      status: 'completed',
      completedIds: nextJob.trackIds,
    });
    scheduleJobRemoval(nextJob.id);
    processNextJob();
    return;
  }

  // Start downloading
  updateJob(nextJob.id, {
    status: 'downloading',
    completedIds: nextJob.trackIds.filter(id => offlineIds.has(id)),
  });

  currentAbortController = new AbortController();
  const abortSignal = currentAbortController.signal;

  let succeeded = 0;
  let failed = 0;

  for (let i = 0; i < tracksToDownload.length; i++) {
    // Check for cancellation
    if (abortSignal.aborted) {
      break;
    }

    const trackId = tracksToDownload[i];

    updateJob(nextJob.id, {
      currentTrackId: trackId,
      currentProgress: 0,
    });

    try {
      log.info('Downloading track', i + 1, 'of', tracksToDownload.length, ':', trackId);
      await offlineService.downloadTrackForOffline(
        trackId,
        (progress) => {
          // Use throttled update to avoid state update storms
          throttledProgressUpdate(nextJob.id, progress.percentage);
        },
        // Surfaced in the UI so a deliberately slowed download doesn't read as a stall.
        (throttling) => {
          const job = useDownloadStore.getState().jobs.get(nextJob.id);
          if (job && job.throttled !== throttling) {
            updateJob(nextJob.id, { throttled: throttling });
          }
        }
      );

      succeeded++;
      log.info('Track completed:', trackId);

      // Update completed IDs
      const currentJob = useDownloadStore.getState().jobs.get(nextJob.id);
      if (currentJob) {
        updateJob(nextJob.id, {
          completedIds: [...currentJob.completedIds, trackId],
        });
      }
    } catch (error) {
      if (!abortSignal.aborted) {
        log.error(`Failed to download track ${trackId}:`, error);
        failed++;

        const currentJob = useDownloadStore.getState().jobs.get(nextJob.id);
        if (currentJob) {
          updateJob(nextJob.id, {
            failedIds: [...currentJob.failedIds, trackId],
          });
        }
      }
    }
  }

  currentAbortController = null;

  // Check if job was cancelled
  const finalJob = useDownloadStore.getState().jobs.get(nextJob.id);
  if (finalJob && finalJob.status !== 'cancelled') {
    const finalStatus = failed > 0 && succeeded === 0 ? 'failed' : 'completed';
    log.info('Job finished:', nextJob.id, 'status:', finalStatus, 'succeeded:', succeeded, 'failed:', failed);

    updateJob(nextJob.id, {
      status: finalStatus,
      currentTrackId: null,
      currentProgress: 0,
      error: failed > 0 ? `${failed} track(s) failed to download` : undefined,
    });

    // Show toast notification for download completion
    if (finalStatus === 'completed' && succeeded > 0) {
      if (failed > 0) {
        showWarning(`Downloaded ${succeeded} tracks, ${failed} failed`, {
          description: nextJob.name,
        });
      } else {
        showSuccess(`Downloaded ${succeeded} tracks for offline`, {
          description: nextJob.name,
        });
      }
    } else if (finalStatus === 'failed') {
      showError('Download failed', {
        description: `Failed to download tracks from "${nextJob.name}"`,
      });
    }

    // Schedule removal after completion
    scheduleJobRemoval(nextJob.id);
  }

  // Process next job
  processNextJob();
}

function updateJob(id: string, updates: Partial<DownloadJob>) {
  const state = useDownloadStore.getState();
  const job = state.jobs.get(id);
  if (!job) return;

  const updatedJob = { ...job, ...updates };
  const newJobs = new Map(state.jobs);
  newJobs.set(id, updatedJob);
  useDownloadStore.setState({ jobs: newJobs });

  // Persist significant status changes to IndexedDB (not progress updates)
  if (updates.status || updates.completedIds || updates.failedIds) {
    persistJob(updatedJob).catch((err) =>
      log.error('Failed to persist job:', err)
    );
  }
}

function scheduleJobRemoval(id: string) {
  // Keep completed jobs visible for a few seconds before auto-removing
  setTimeout(async () => {
    const state = useDownloadStore.getState();
    const job = state.jobs.get(id);
    if (job && (job.status === 'completed' || job.status === 'failed')) {
      const newJobs = new Map(state.jobs);
      newJobs.delete(id);
      useDownloadStore.setState({ jobs: newJobs });

      // Also remove from IndexedDB
      await removePersistedJob(id).catch((err) =>
        log.error('Failed to remove persisted job:', err)
      );
    }
  }, 5000);
}

// Helper to generate job IDs
export function getPlaylistJobId(playlistId: string): string {
  return `playlist-${playlistId}`;
}

export function getSmartPlaylistJobId(playlistId: string): string {
  return `smart-playlist-${playlistId}`;
}

export function getAlbumJobId(artist: string, album: string): string {
  return `album-${artist}-${album}`;
}
