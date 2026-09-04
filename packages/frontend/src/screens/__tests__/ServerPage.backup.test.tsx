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

import { ServerPage } from '../ServerPage';

// Every other panel is stubbed: this asserts reachability, not their contents.
vi.mock('../../panels/server/SystemStatus', () => ({ SystemStatus: () => null }));
vi.mock('../../panels/server/DiscoverySources', () => ({ DiscoverySources: () => null }));
vi.mock('../../panels/server/ApiKeyStatus', () => ({ ApiKeyStatus: () => null }));
vi.mock('../../panels/server/ServerTokenSettings', () => ({ ServerTokenSettings: () => null }));
vi.mock('../../panels/server/ProfileSettings', () => ({ ProfileSettings: () => null }));
vi.mock('../../panels/server/LastfmSettings', () => ({ LastfmSettings: () => null }));
vi.mock('../../panels/server/DebugSettings', () => ({ DebugSettings: () => null }));
vi.mock('../../panels/server/RemoteLogsPanel', () => ({ RemoteLogsPanel: () => null }));
vi.mock('../../panels/server/BackgroundJobs', () => ({ BackgroundJobs: () => null }));

vi.mock('../../panels/server/BackupSettings', () => ({
  BackupSettings: () => <div data-testid="backup-settings-mounted" />,
}));
vi.mock('../../panels/server/BackupRestore', () => ({
  BackupRestore: () => <div data-testid="backup-restore-mounted" />,
}));

afterEach(cleanup);

describe('ServerPage mounts the backup surface', () => {
  it('renders the backup settings panel', () => {
    render(<ServerPage />);
    expect(screen.getByTestId('backup-settings-mounted')).toBeTruthy();
  });

  it('renders the restore panel', () => {
    render(<ServerPage />);
    expect(screen.getByTestId('backup-restore-mounted')).toBeTruthy();
  });

  it('gives them a labelled section, so they are findable', () => {
    render(<ServerPage />);
    expect(screen.getByText(/^backup$/i)).toBeTruthy();
  });
});
