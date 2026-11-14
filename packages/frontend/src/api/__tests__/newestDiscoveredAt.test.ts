import { describe, expect, it } from 'vitest';
import { newestDiscoveredAt } from '../discovery';

describe('newestDiscoveredAt (ADR-0179)', () => {
  it('is null for nothing shown', () => {
    expect(newestDiscoveredAt([])).toBeNull();
  });

  it('compares instants, not text, and returns the server string unchanged', () => {
    // Python drops zero microseconds, so "…:00" and "…:00.5" do not sort correctly as text.
    const rows = [
      { discovered_at: '2026-11-14T10:00:00.500000' },
      { discovered_at: '2026-11-14T10:00:01' },
      { discovered_at: '2026-11-14T09:59:59.999999' },
    ];
    expect(newestDiscoveredAt(rows)).toBe('2026-11-14T10:00:01');
  });
});
