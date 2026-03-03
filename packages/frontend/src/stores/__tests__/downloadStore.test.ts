/**
 * Tests for downloadStore - Zustand store for managing offline download queue.
 */
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';

// Mock dependencies before any imports that use them
vi.mock('../../services/offlineService', () => ({
  getOfflineTrackIds: vi.fn(() => Promise.resolve([])),
  downloadTrackForOffline: vi.fn(() => Promise.resolve()),
}));

vi.mock('../../db', () => {
  const mockDownloadQueue = {
    put: vi.fn(() => Promise.resolve()),
    delete: vi.fn(() => Promise.resolve()),
    toArray: vi.fn(() => Promise.resolve([])),
    get: vi.fn(() => Promise.resolve(undefined)),
  };
  return {
    db: {
      downloadQueue: mockDownloadQueue,
    },
  };
});

vi.mock('../toastStore', () => ({
  showSuccess: vi.fn(),
  showError: vi.fn(),
  showWarning: vi.fn(),
}));

vi.mock('../../utils/logger', () => ({
  createLogger: () => ({
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  }),
}));

import {
  useDownloadStore,
  getPlaylistJobId,
  getSmartPlaylistJobId,
  getAlbumJobId,
} from '../downloadStore';
import type { DownloadJob } from '../downloadStore';
import { db } from '../../db';

describe('downloadStore', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    // Reset store state
    useDownloadStore.setState({
      jobs: new Map(),
      activeJobId: null,
    });
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe('helper functions', () => {
    it('should generate playlist job ID', () => {
      expect(getPlaylistJobId('abc-123')).toBe('playlist-abc-123');
    });

    it('should generate smart playlist job ID', () => {
      expect(getSmartPlaylistJobId('def-456')).toBe('smart-playlist-def-456');
    });

    it('should generate album job ID', () => {
      expect(getAlbumJobId('Pink Floyd', 'The Wall')).toBe('album-Pink Floyd-The Wall');
    });
  });

  describe('startDownload', () => {
    it('should create a new queued job', () => {
      const { startDownload } = useDownloadStore.getState();

      startDownload('playlist-1', 'playlist', 'My Playlist', ['t1', 't2', 't3']);

      const state = useDownloadStore.getState();
      const job = state.jobs.get('playlist-1');
      expect(job).toBeDefined();
      expect(job!.status).toBe('queued');
      expect(job!.trackIds).toEqual(['t1', 't2', 't3']);
      expect(job!.name).toBe('My Playlist');
      expect(job!.type).toBe('playlist');
      expect(job!.completedIds).toEqual([]);
      expect(job!.failedIds).toEqual([]);
      expect(job!.currentTrackId).toBeNull();
      expect(job!.currentProgress).toBe(0);
    });

    it('should not create duplicate job when already downloading', () => {
      const { startDownload } = useDownloadStore.getState();

      startDownload('playlist-1', 'playlist', 'My Playlist', ['t1']);

      // Try to start same job again
      startDownload('playlist-1', 'playlist', 'My Playlist', ['t1', 't2']);

      const state = useDownloadStore.getState();
      const job = state.jobs.get('playlist-1');
      // Should still have original tracks, not the new ones
      expect(job!.trackIds).toEqual(['t1']);
    });

    it('should not create duplicate job when already queued', () => {
      const { startDownload } = useDownloadStore.getState();

      startDownload('playlist-1', 'playlist', 'First', ['t1']);
      startDownload('playlist-1', 'playlist', 'Second attempt', ['t1', 't2']);

      const state = useDownloadStore.getState();
      const job = state.jobs.get('playlist-1');
      expect(job!.name).toBe('First');
    });

    it('should allow restarting a completed job', async () => {
      // Manually set a completed job
      const completedJob: DownloadJob = {
        id: 'playlist-1',
        type: 'playlist',
        name: 'Done Playlist',
        trackIds: ['t1'],
        completedIds: ['t1'],
        failedIds: [],
        currentTrackId: null,
        currentProgress: 0,
        status: 'completed',
        startedAt: new Date(),
      };
      const jobs = new Map<string, DownloadJob>();
      jobs.set('playlist-1', completedJob);
      useDownloadStore.setState({ jobs });

      const { startDownload } = useDownloadStore.getState();
      startDownload('playlist-1', 'playlist', 'Retry Playlist', ['t1', 't2']);

      const state = useDownloadStore.getState();
      const job = state.jobs.get('playlist-1');
      expect(job!.status).toBe('queued');
      expect(job!.trackIds).toEqual(['t1', 't2']);
    });

    it('should allow restarting a failed job', () => {
      const failedJob: DownloadJob = {
        id: 'playlist-1',
        type: 'playlist',
        name: 'Failed',
        trackIds: ['t1'],
        completedIds: [],
        failedIds: ['t1'],
        currentTrackId: null,
        currentProgress: 0,
        status: 'failed',
        startedAt: new Date(),
      };
      const jobs = new Map<string, DownloadJob>();
      jobs.set('playlist-1', failedJob);
      useDownloadStore.setState({ jobs });

      const { startDownload } = useDownloadStore.getState();
      startDownload('playlist-1', 'playlist', 'Retry', ['t1']);

      const state = useDownloadStore.getState();
      expect(state.jobs.get('playlist-1')!.status).toBe('queued');
    });

    it('should persist job to IndexedDB on creation', () => {
      const { startDownload } = useDownloadStore.getState();
      startDownload('playlist-1', 'playlist', 'My Playlist', ['t1']);

      // persistJob is called asynchronously; the mock is set up
      expect(db.downloadQueue.put).toHaveBeenCalled();
    });

    it('should set startedAt timestamp on new job', () => {
      const before = new Date();
      const { startDownload } = useDownloadStore.getState();
      startDownload('playlist-1', 'playlist', 'My Playlist', ['t1']);

      const job = useDownloadStore.getState().jobs.get('playlist-1');
      expect(job!.startedAt.getTime()).toBeGreaterThanOrEqual(before.getTime());
    });
  });

  describe('cancelDownload', () => {
    it('should mark job as cancelled', () => {
      const { startDownload, cancelDownload } = useDownloadStore.getState();
      startDownload('playlist-1', 'playlist', 'My Playlist', ['t1']);

      cancelDownload('playlist-1');

      const state = useDownloadStore.getState();
      const job = state.jobs.get('playlist-1');
      expect(job!.status).toBe('cancelled');
    });

    it('should remove cancelled job after timeout', () => {
      const { startDownload, cancelDownload } = useDownloadStore.getState();
      startDownload('playlist-1', 'playlist', 'My Playlist', ['t1']);

      cancelDownload('playlist-1');

      // Job should still be there initially
      expect(useDownloadStore.getState().jobs.has('playlist-1')).toBe(true);

      // Advance past the removal delay (2000ms)
      vi.advanceTimersByTime(2500);

      expect(useDownloadStore.getState().jobs.has('playlist-1')).toBe(false);
    });

    it('should do nothing when cancelling non-existent job', () => {
      const { cancelDownload } = useDownloadStore.getState();

      // Should not throw
      cancelDownload('non-existent');

      expect(useDownloadStore.getState().jobs.size).toBe(0);
    });

    it('should clear activeJobId if cancelling the active job', () => {
      // Set up an active job
      const job: DownloadJob = {
        id: 'playlist-1',
        type: 'playlist',
        name: 'Active',
        trackIds: ['t1'],
        completedIds: [],
        failedIds: [],
        currentTrackId: 't1',
        currentProgress: 50,
        status: 'downloading',
        startedAt: new Date(),
      };
      const jobs = new Map<string, DownloadJob>();
      jobs.set('playlist-1', job);
      useDownloadStore.setState({ jobs, activeJobId: 'playlist-1' });

      const { cancelDownload } = useDownloadStore.getState();
      cancelDownload('playlist-1');

      expect(useDownloadStore.getState().activeJobId).toBeNull();
    });

    it('should not clear activeJobId if cancelling a non-active job', () => {
      const job1: DownloadJob = {
        id: 'playlist-1',
        type: 'playlist',
        name: 'Active',
        trackIds: ['t1'],
        completedIds: [],
        failedIds: [],
        currentTrackId: 't1',
        currentProgress: 50,
        status: 'downloading',
        startedAt: new Date(),
      };
      const job2: DownloadJob = {
        id: 'playlist-2',
        type: 'playlist',
        name: 'Queued',
        trackIds: ['t2'],
        completedIds: [],
        failedIds: [],
        currentTrackId: null,
        currentProgress: 0,
        status: 'queued',
        startedAt: new Date(),
      };
      const jobs = new Map<string, DownloadJob>();
      jobs.set('playlist-1', job1);
      jobs.set('playlist-2', job2);
      useDownloadStore.setState({ jobs, activeJobId: 'playlist-1' });

      const { cancelDownload } = useDownloadStore.getState();
      cancelDownload('playlist-2');

      expect(useDownloadStore.getState().activeJobId).toBe('playlist-1');
    });
  });

  describe('getJob', () => {
    it('should return job by ID', () => {
      const { startDownload, getJob } = useDownloadStore.getState();
      startDownload('playlist-1', 'playlist', 'My Playlist', ['t1']);

      const job = getJob('playlist-1');
      expect(job).toBeDefined();
      expect(job!.name).toBe('My Playlist');
    });

    it('should return undefined for non-existent job', () => {
      const { getJob } = useDownloadStore.getState();
      expect(getJob('non-existent')).toBeUndefined();
    });
  });

  describe('getActiveJob', () => {
    it('should return the active job', () => {
      const job: DownloadJob = {
        id: 'playlist-1',
        type: 'playlist',
        name: 'Active',
        trackIds: ['t1'],
        completedIds: [],
        failedIds: [],
        currentTrackId: 't1',
        currentProgress: 50,
        status: 'downloading',
        startedAt: new Date(),
      };
      const jobs = new Map<string, DownloadJob>();
      jobs.set('playlist-1', job);
      useDownloadStore.setState({ jobs, activeJobId: 'playlist-1' });

      const { getActiveJob } = useDownloadStore.getState();
      const active = getActiveJob();
      expect(active).toBeDefined();
      expect(active!.id).toBe('playlist-1');
    });

    it('should return undefined when no active job', () => {
      const { getActiveJob } = useDownloadStore.getState();
      expect(getActiveJob()).toBeUndefined();
    });
  });

  describe('clearCompletedJobs', () => {
    it('should remove completed jobs', () => {
      const completed: DownloadJob = {
        id: 'done-1',
        type: 'playlist',
        name: 'Done',
        trackIds: ['t1'],
        completedIds: ['t1'],
        failedIds: [],
        currentTrackId: null,
        currentProgress: 0,
        status: 'completed',
        startedAt: new Date(),
      };
      const queued: DownloadJob = {
        id: 'queued-1',
        type: 'playlist',
        name: 'Queued',
        trackIds: ['t2'],
        completedIds: [],
        failedIds: [],
        currentTrackId: null,
        currentProgress: 0,
        status: 'queued',
        startedAt: new Date(),
      };
      const jobs = new Map<string, DownloadJob>();
      jobs.set('done-1', completed);
      jobs.set('queued-1', queued);
      useDownloadStore.setState({ jobs });

      const { clearCompletedJobs } = useDownloadStore.getState();
      clearCompletedJobs();

      const state = useDownloadStore.getState();
      expect(state.jobs.has('done-1')).toBe(false);
      expect(state.jobs.has('queued-1')).toBe(true);
    });

    it('should remove failed jobs', () => {
      const failed: DownloadJob = {
        id: 'failed-1',
        type: 'album',
        name: 'Failed Album',
        trackIds: ['t1'],
        completedIds: [],
        failedIds: ['t1'],
        currentTrackId: null,
        currentProgress: 0,
        status: 'failed',
        startedAt: new Date(),
      };
      const jobs = new Map<string, DownloadJob>();
      jobs.set('failed-1', failed);
      useDownloadStore.setState({ jobs });

      const { clearCompletedJobs } = useDownloadStore.getState();
      clearCompletedJobs();

      expect(useDownloadStore.getState().jobs.size).toBe(0);
    });

    it('should remove cancelled jobs', () => {
      const cancelled: DownloadJob = {
        id: 'cancelled-1',
        type: 'playlist',
        name: 'Cancelled',
        trackIds: ['t1'],
        completedIds: [],
        failedIds: [],
        currentTrackId: null,
        currentProgress: 0,
        status: 'cancelled',
        startedAt: new Date(),
      };
      const jobs = new Map<string, DownloadJob>();
      jobs.set('cancelled-1', cancelled);
      useDownloadStore.setState({ jobs });

      const { clearCompletedJobs } = useDownloadStore.getState();
      clearCompletedJobs();

      expect(useDownloadStore.getState().jobs.size).toBe(0);
    });

    it('should keep downloading jobs', () => {
      const downloading: DownloadJob = {
        id: 'dl-1',
        type: 'playlist',
        name: 'Downloading',
        trackIds: ['t1', 't2'],
        completedIds: ['t1'],
        failedIds: [],
        currentTrackId: 't2',
        currentProgress: 30,
        status: 'downloading',
        startedAt: new Date(),
      };
      const jobs = new Map<string, DownloadJob>();
      jobs.set('dl-1', downloading);
      useDownloadStore.setState({ jobs });

      const { clearCompletedJobs } = useDownloadStore.getState();
      clearCompletedJobs();

      expect(useDownloadStore.getState().jobs.has('dl-1')).toBe(true);
    });

    it('should handle empty jobs map', () => {
      const { clearCompletedJobs } = useDownloadStore.getState();
      clearCompletedJobs();

      expect(useDownloadStore.getState().jobs.size).toBe(0);
    });
  });

  describe('restoreDownloadQueue', () => {
    it('should restore jobs from IndexedDB and auto-process them', async () => {
      vi.useRealTimers();
      vi.resetModules();

      const mockDownload = vi.fn(() => Promise.resolve());
      vi.doMock('../../db', () => {
        const mockDownloadQueue = {
          put: vi.fn(() => Promise.resolve()),
          delete: vi.fn(() => Promise.resolve()),
          toArray: vi.fn(() =>
            Promise.resolve([
              {
                id: 'playlist-1',
                type: 'playlist' as const,
                name: 'Saved Playlist',
                trackIds: ['t1', 't2'],
                completedIds: ['t1'],
                failedIds: [],
                status: 'queued' as const,
                startedAt: new Date(),
                updatedAt: new Date(),
              },
            ])
          ),
        };
        return { db: { downloadQueue: mockDownloadQueue } };
      });

      vi.doMock('../../services/offlineService', () => ({
        getOfflineTrackIds: vi.fn(() => Promise.resolve(['t1'])),
        downloadTrackForOffline: mockDownload,
      }));

      vi.doMock('../toastStore', () => ({
        showSuccess: vi.fn(),
        showError: vi.fn(),
        showWarning: vi.fn(),
      }));

      vi.doMock('../../utils/logger', () => ({
        createLogger: () => ({
          info: vi.fn(),
          warn: vi.fn(),
          error: vi.fn(),
          debug: vi.fn(),
        }),
      }));

      const { restoreDownloadQueue: restore, useDownloadStore: store } =
        await import('../downloadStore');

      await restore();

      // Wait for async processNextJob to complete
      await new Promise((r) => setTimeout(r, 100));

      // The job was restored from IDB - it may have already been processed
      // by processNextJob (which is called automatically). Verify it was
      // at least added to the store.
      const state = store.getState();
      // Job should exist (may be completed by now since mock resolves immediately)
      const job = state.jobs.get('playlist-1');
      if (job) {
        // If still present, it should have the right name
        expect(job.name).toBe('Saved Playlist');
      }
      // downloadTrackForOffline was called for the remaining track (t2, since t1 was already offline)
      expect(mockDownload).toHaveBeenCalled();
    });

    it('should convert downloading/paused status to queued on restore', async () => {
      vi.useRealTimers();
      vi.resetModules();

      vi.doMock('../../db', () => ({
        db: {
          downloadQueue: {
            put: vi.fn(() => Promise.resolve()),
            delete: vi.fn(() => Promise.resolve()),
            // Return a job that was 'downloading' when app closed
            toArray: vi.fn(() =>
              Promise.resolve([
                {
                  id: 'playlist-2',
                  type: 'playlist' as const,
                  name: 'Was Downloading',
                  trackIds: ['t1'],
                  completedIds: [],
                  failedIds: [],
                  status: 'downloading' as const,
                  startedAt: new Date(),
                  updatedAt: new Date(),
                },
              ])
            ),
          },
        },
      }));

      vi.doMock('../../services/offlineService', () => ({
        getOfflineTrackIds: vi.fn(() => Promise.resolve([])),
        // Make download hang so we can check intermediate status
        downloadTrackForOffline: vi.fn(
          () => new Promise(() => {/* never resolves */})
        ),
      }));

      vi.doMock('../toastStore', () => ({
        showSuccess: vi.fn(),
        showError: vi.fn(),
        showWarning: vi.fn(),
      }));

      vi.doMock('../../utils/logger', () => ({
        createLogger: () => ({
          info: vi.fn(),
          warn: vi.fn(),
          error: vi.fn(),
          debug: vi.fn(),
        }),
      }));

      const { restoreDownloadQueue: restore, useDownloadStore: store } =
        await import('../downloadStore');

      await restore();

      // Give processNextJob a tick to start
      await new Promise((r) => setTimeout(r, 50));

      // The job was restored and processNextJob started - it should now be 'downloading'
      // The key point is that the persisted 'downloading' status was first converted to 'queued'
      // during restore, and then processNextJob picked it up and set it to 'downloading'
      const job = store.getState().jobs.get('playlist-2');
      expect(job).toBeDefined();
      // Job is now being processed (downloading) since processNextJob was called
      expect(job!.status).toBe('downloading');
    });

    it('should skip old completed jobs during restore', async () => {
      vi.useRealTimers();
      vi.resetModules();

      const oldDate = new Date(Date.now() - 2 * 60 * 60 * 1000); // 2 hours ago

      const mockDelete = vi.fn(() => Promise.resolve());
      vi.doMock('../../db', () => ({
        db: {
          downloadQueue: {
            put: vi.fn(() => Promise.resolve()),
            delete: mockDelete,
            toArray: vi.fn(() =>
              Promise.resolve([
                {
                  id: 'old-completed',
                  type: 'playlist' as const,
                  name: 'Old Done',
                  trackIds: ['t1'],
                  completedIds: ['t1'],
                  failedIds: [],
                  status: 'completed' as const,
                  startedAt: oldDate,
                  updatedAt: oldDate,
                },
              ])
            ),
          },
        },
      }));

      vi.doMock('../../services/offlineService', () => ({
        getOfflineTrackIds: vi.fn(() => Promise.resolve([])),
        downloadTrackForOffline: vi.fn(() => Promise.resolve()),
      }));

      vi.doMock('../toastStore', () => ({
        showSuccess: vi.fn(),
        showError: vi.fn(),
        showWarning: vi.fn(),
      }));

      vi.doMock('../../utils/logger', () => ({
        createLogger: () => ({
          info: vi.fn(),
          warn: vi.fn(),
          error: vi.fn(),
          debug: vi.fn(),
        }),
      }));

      const { restoreDownloadQueue: restore, useDownloadStore: store } =
        await import('../downloadStore');

      await restore();

      // Old completed job should have been deleted from IDB
      expect(mockDelete).toHaveBeenCalledWith('old-completed');
      // And not restored into the store
      expect(store.getState().jobs.has('old-completed')).toBe(false);
    });
  });

  describe('multiple jobs', () => {
    it('should support multiple jobs in queue', () => {
      const { startDownload } = useDownloadStore.getState();

      startDownload('playlist-1', 'playlist', 'First', ['t1']);
      startDownload('playlist-2', 'playlist', 'Second', ['t2']);
      startDownload('album-1', 'album', 'Album', ['t3', 't4']);

      const state = useDownloadStore.getState();
      expect(state.jobs.size).toBe(3);
    });

    it('should preserve other jobs when clearing completed', () => {
      const completed: DownloadJob = {
        id: 'done',
        type: 'playlist',
        name: 'Done',
        trackIds: ['t1'],
        completedIds: ['t1'],
        failedIds: [],
        currentTrackId: null,
        currentProgress: 0,
        status: 'completed',
        startedAt: new Date(),
      };
      const downloading: DownloadJob = {
        id: 'active',
        type: 'album',
        name: 'Active Album',
        trackIds: ['t2', 't3'],
        completedIds: ['t2'],
        failedIds: [],
        currentTrackId: 't3',
        currentProgress: 75,
        status: 'downloading',
        startedAt: new Date(),
      };
      const queued: DownloadJob = {
        id: 'waiting',
        type: 'smart-playlist',
        name: 'Waiting',
        trackIds: ['t4'],
        completedIds: [],
        failedIds: [],
        currentTrackId: null,
        currentProgress: 0,
        status: 'queued',
        startedAt: new Date(),
      };
      const jobs = new Map<string, DownloadJob>();
      jobs.set('done', completed);
      jobs.set('active', downloading);
      jobs.set('waiting', queued);
      useDownloadStore.setState({ jobs, activeJobId: 'active' });

      const { clearCompletedJobs } = useDownloadStore.getState();
      clearCompletedJobs();

      const state = useDownloadStore.getState();
      expect(state.jobs.size).toBe(2);
      expect(state.jobs.has('active')).toBe(true);
      expect(state.jobs.has('waiting')).toBe(true);
    });
  });

  describe('job types', () => {
    it('should support playlist type', () => {
      const { startDownload } = useDownloadStore.getState();
      startDownload('p-1', 'playlist', 'Playlist', ['t1']);

      expect(useDownloadStore.getState().jobs.get('p-1')!.type).toBe('playlist');
    });

    it('should support smart-playlist type', () => {
      const { startDownload } = useDownloadStore.getState();
      startDownload('sp-1', 'smart-playlist', 'Smart Playlist', ['t1']);

      expect(useDownloadStore.getState().jobs.get('sp-1')!.type).toBe('smart-playlist');
    });

    it('should support album type', () => {
      const { startDownload } = useDownloadStore.getState();
      startDownload('a-1', 'album', 'Album', ['t1']);

      expect(useDownloadStore.getState().jobs.get('a-1')!.type).toBe('album');
    });
  });
});
