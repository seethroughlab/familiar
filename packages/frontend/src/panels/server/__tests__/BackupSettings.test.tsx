/* @vitest-environment jsdom */
/**
 * The defect these guard against is not "the panel renders wrong" — it is
 * "nothing calls the endpoint". `s3_backup_enabled` was typed in the settings
 * client and rendered by no component for months, so backups could not be turned
 * on and the failure was silent. A test that only asserted markup would have
 * passed the whole time.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, fireEvent, cleanup } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';

import { BackupSettings } from '../BackupSettings';
import { BackupRestore } from '../BackupRestore';

const getSettings = vi.fn();
const updateSettings = vi.fn();
const getStatus = vi.fn();
const getEstimate = vi.fn();
const getManifest = vi.fn();
const getRestoreProgress = vi.fn();
const run = vi.fn();
const validate = vi.fn();
const downloadAndRestore = vi.fn();
const initiateRestore = vi.fn();

vi.mock('../../../api', () => ({
  appSettingsApi: {
    get: () => getSettings(),
    update: (u: unknown) => updateSettings(u),
  },
  s3BackupApi: {
    getStatus: () => getStatus(),
    getEstimate: () => getEstimate(),
    getManifest: () => getManifest(),
    getRestoreProgress: () => getRestoreProgress(),
    run: () => run(),
    cancel: vi.fn(),
    validate: (p: unknown) => validate(p),
    initiateRestore: () => initiateRestore(),
    checkRestore: vi.fn(),
    downloadAndRestore: () => downloadAndRestore(),
  },
}));

function wrap(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const CONFIGURED = {
  s3_backup_configured: true,
  s3_backup_enabled: false,
  s3_backup_bucket: 'familiar-backups',
  s3_backup_region: 'us-east-1',
  s3_backup_prefix: '',
  s3_backup_schedule: 'weekly',
};

afterEach(cleanup);

beforeEach(() => {
  vi.clearAllMocks();
  getSettings.mockResolvedValue({ ...CONFIGURED });
  updateSettings.mockResolvedValue({ ...CONFIGURED });
  getStatus.mockResolvedValue({ enabled: false, is_running: false, last_backup: null, progress: null });
  getEstimate.mockResolvedValue({
    storage_gb: 412.5,
    monthly_cost: 0.41,
    initial_upload_cost: 1.2,
    estimated_restore_cost: 1.03,
    by_category: {},
  });
  getManifest.mockResolvedValue({ file_count: 26469, last_backup_at: '2026-09-01T03:30:00Z', by_category: {} });
  getRestoreProgress.mockResolvedValue({ status: 'idle', phase: 'idle', files_total: 0, files_uploaded: 0, files_skipped: 0, bytes_uploaded: 0, current_file: null, started_at: null, error: null });
});

describe('BackupSettings', () => {
  it('turning the toggle on actually writes s3_backup_enabled', async () => {
    // The whole bug in one assertion: the scheduler's first line is
    // `if not settings.s3_backup_enabled: return`, so without this call
    // nothing ever runs.
    wrap(<BackupSettings />);
    const toggle = await screen.findByRole('switch', { name: /scheduled backups/i });

    fireEvent.click(toggle);

    await waitFor(() => expect(updateSettings).toHaveBeenCalledWith({ s3_backup_enabled: true }));
  });

  it('offers no toggle at all when credentials are absent, and says where they go', async () => {
    getSettings.mockResolvedValue({ ...CONFIGURED, s3_backup_configured: false });
    wrap(<BackupSettings />);

    expect(await screen.findByText(/credentials not configured/i)).toBeTruthy();
    expect(screen.queryByRole('switch')).toBeNull();
    expect(screen.getByText(/S3_BACKUP_BUCKET/)).toBeTruthy();
  });

  it('shows what the backup costs, since Deep Archive pricing is the reason to use it', async () => {
    wrap(<BackupSettings />);
    expect(await screen.findByText(/412\.5 GB/)).toBeTruthy();
    expect(screen.getByText(/\$0\.41\/month/)).toBeTruthy();
  });

  it('"Back up now" calls the endpoint that had no caller', async () => {
    run.mockResolvedValue({ status: 'started' });
    wrap(<BackupSettings />);

    fireEvent.click(await screen.findByRole('button', { name: /back up now/i }));

    await waitFor(() => expect(run).toHaveBeenCalled());
  });
});

describe('BackupRestore', () => {
  it('will not restore until the bucket name is typed', async () => {
    // Guards a mis-click, not an attacker — Familiar runs on a private network.
    wrap(<BackupRestore />);
    fireEvent.click(await screen.findByRole('button', { name: /show/i }));

    const restore = screen.getByRole('button', { name: /restore now/i });
    expect(restore.hasAttribute('disabled')).toBe(true);

    fireEvent.change(screen.getByLabelText(/type the bucket name/i), { target: { value: 'familiar-backups' } });
    await waitFor(() => expect(restore.hasAttribute('disabled')).toBe(false));
  });

  it('a wrong bucket name leaves it disabled', async () => {
    wrap(<BackupRestore />);
    fireEvent.click(await screen.findByRole('button', { name: /show/i }));

    fireEvent.change(screen.getByLabelText(/type the bucket name/i), { target: { value: 'familiar-backup' } });
    expect(screen.getByRole('button', { name: /restore now/i }).hasAttribute('disabled')).toBe(true);
    expect(downloadAndRestore).not.toHaveBeenCalled();
  });

  it('says that a safety dump is taken, because the restore now takes one', async () => {
    wrap(<BackupRestore />);
    fireEvent.click(await screen.findByRole('button', { name: /show/i }));

    expect(screen.getByText(/restore-safety/)).toBeTruthy();
    expect(screen.getByText(/aborts if that fails/i)).toBeTruthy();
  });

  it('renders nothing when S3 was never configured', async () => {
    getSettings.mockResolvedValue({ ...CONFIGURED, s3_backup_configured: false });
    const { container } = wrap(<BackupRestore />);
    await waitFor(() => expect(container.innerHTML).toBe(''));
  });
});
