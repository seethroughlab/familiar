/* @vitest-environment jsdom */
/**
 * That the Server destination actually *mounts* the backup panels.
 *
 * This is the test the original defect needed and nobody had. `s3_backup_enabled`
 * was typed in the settings client and reachable through the API for months;
 * what was missing was a component rendering it. A panel test cannot catch that
 * — it renders the panel itself, so it passes whether or not any page mounts it.
 *
 * The same shape has bitten this project repeatedly: an affordance whose
 * destination is not mounted (familiar #70, #74, #76). Asserting the panel
 * renders is not the same as asserting it is reachable.
 */
import { render, screen, cleanup } from '@testing-library/react';
import { describe, expect, it, vi, afterEach } from 'vitest';

import { BackupSection } from '../server/sections';

// The two panels under test are stubbed to markers; this asserts reachability, not their contents.
vi.mock('../../panels/server/BackupSettings', () => ({
  BackupSettings: () => <div data-testid="backup-settings-mounted" />,
}));
vi.mock('../../panels/server/BackupRestore', () => ({
  BackupRestore: () => <div data-testid="backup-restore-mounted" />,
}));
// Every other panel the sections file imports is stubbed too.
vi.mock('../../panels/server/SystemStatus', () => ({ SystemStatus: () => null }));
vi.mock('../../panels/server/ProviderCards', () => ({ ProviderCards: () => null, SourceHealth: () => null }));
vi.mock('../../panels/server/ServerTokenSettings', () => ({ ServerTokenSettings: () => null }));
vi.mock('../../panels/server/ProfileSettings', () => ({ ProfileSettings: () => null }));
vi.mock('../../panels/server/DebugSettings', () => ({ DebugSettings: () => null }));
vi.mock('../../panels/server/RemoteLogsPanel', () => ({ RemoteLogsPanel: () => null }));
vi.mock('../../panels/server/BackgroundJobs', () => ({ BackgroundJobs: () => null }));
vi.mock('../../panels/tools/DataManagement', () => ({ DataManagement: () => null }));
vi.mock('../../stores/backgroundJobsStore', () => ({ useBackgroundJobsStore: () => ({ activeCount: 0, startPolling: () => {}, stopPolling: () => {} }) }));
vi.mock('../../api', () => ({ systemApi: { health: vi.fn() } }));

afterEach(cleanup);

describe('Server → Backup mounts the backup surface (ADR-0126 point 6)', () => {
  it('renders the backup settings panel', () => {
    render(<BackupSection />);
    expect(screen.getByTestId('backup-settings-mounted')).toBeTruthy();
  });

  it('renders the restore panel', () => {
    render(<BackupSection />);
    expect(screen.getByTestId('backup-restore-mounted')).toBeTruthy();
  });

  it('is the S3 installation backup and says so — the profile transfer is under People', () => {
    render(<BackupSection />);
    expect(screen.getByRole('heading', { name: 'Backup' })).toBeTruthy();
    expect(screen.getByText(/installation backup to S3/)).toBeTruthy();
  });
});
