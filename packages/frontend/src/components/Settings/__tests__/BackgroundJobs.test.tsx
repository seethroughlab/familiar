/* @vitest-environment jsdom */
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { BackgroundJobs } from '../BackgroundJobs';

const startPolling = vi.fn();
const stopPolling = vi.fn();

let state: { jobs: unknown[]; activeCount: number };

vi.mock('../../../stores/backgroundJobsStore', () => ({
  useBackgroundJobsStore: () => ({ ...state, startPolling, stopPolling }),
}));

describe('BackgroundJobs', () => {
  it('renders nothing at all when no job is running', () => {
    // Not just "no progress bars": the *heading* must be absent too. Returning null from inside a
    // section the page had already opened left a "JOBS" label over empty space on the Server
    // destination, which is the empty-section defect that page is explicitly meant not to ship.
    state = { jobs: [], activeCount: 0 };
    const { container } = render(<BackgroundJobs />);

    expect(container.innerHTML).toBe('');
    expect(screen.queryByText(/jobs/i)).toBeNull();
  });

  it('shows a running job, its phase and its progress', () => {
    state = {
      activeCount: 1,
      jobs: [{
        type: 'library_sync',
        phase: 'features',
        current_item: 'Boards of Canada — Dayvan Cowboy',
        message: 'working (12 queued)',
        progress: { current: 40, total: 200 },
      }],
    };
    render(<BackgroundJobs />);

    expect(screen.getByText('Jobs')).toBeTruthy();
    expect(screen.getByText('Library Sync')).toBeTruthy();
    expect(screen.getByText('Extracting features')).toBeTruthy();
    expect(screen.getByText('Boards of Canada — Dayvan Cowboy')).toBeTruthy();
    expect(screen.getByText(/40\/200/)).toBeTruthy();
    expect(screen.getByText(/12 queued/)).toBeTruthy();
  });

  it('reports the two job types that have no other indicator anywhere', () => {
    // `library_sync` also shows progress on the Library dashboard. These two do not, which is the
    // whole reason this panel exists rather than the status menu simply being deleted.
    state = {
      activeCount: 2,
      jobs: [
        { type: 'artwork_fetch', progress: { current: 3, total: 9 } },
        { type: 's3_backup', progress: null },
      ],
    };
    render(<BackgroundJobs />);

    expect(screen.getByText('Artwork')).toBeTruthy();
    expect(screen.getByText('S3 Backup')).toBeTruthy();
  });

  it('polls while mounted and stops on unmount', () => {
    // The status menu was always mounted and hosted this polling; nothing else calls it.
    state = { jobs: [], activeCount: 0 };
    const { unmount } = render(<BackgroundJobs />);

    expect(startPolling).toHaveBeenCalled();
    unmount();
    expect(stopPolling).toHaveBeenCalled();
  });
});
