/**
 * `toSyncStatus` is the one transformation the library adapter keeps (ADR-0173 point 6): the
 * schema marks every progress field optional, and the server sends every one, or `null`.
 */
import { describe, expect, it } from 'vitest';

import { toSyncStatus } from '../library';

describe('toSyncStatus', () => {
  it('keeps null progress null', () => {
    expect(toSyncStatus({ status: 'idle', message: 'Idle' }).progress).toBeNull();
  });

  it('fills a partial progress with the server defaults', () => {
    const status = toSyncStatus({
      status: 'running',
      message: 'Reading',
      progress: { phase: 'reading', files_total: 10, files_processed: 4 },
    });
    expect(status.progress).toMatchObject({
      phase: 'reading',
      files_total: 10,
      files_processed: 4,
      analysis_percent: 0,
      errors: [],
      started_at: null,
    });
  });

  it('does not let a default overwrite a value the server sent', () => {
    const status = toSyncStatus({
      status: 'running',
      message: 'Analysing',
      progress: { phase: 'features', analysis_percent: 42.5, errors: ['one'] },
    });
    expect(status.progress?.analysis_percent).toBe(42.5);
    expect(status.progress?.errors).toEqual(['one']);
  });
});
