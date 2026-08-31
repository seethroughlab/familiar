/**
 * The acceptance criterion, in ADR-0099's own terms: a source with a valid key
 * that has failed for nineteen days must not look like a working one.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { DiscoverySources } from '../DiscoverySources';
import { healthApi } from '../../../api/admin';

vi.mock('../../../api/admin', () => ({
  healthApi: { getDiscoverySources: vi.fn() },
}));

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DiscoverySources />
    </QueryClientProvider>,
  );
}

const iso = (daysAgo: number) =>
  new Date(Date.now() - daysAgo * 86_400_000).toISOString();

const source = (over: Partial<Record<string, unknown>> = {}) => ({
  source: 'musicbrainz',
  state: 'working',
  last_success_at: iso(0),
  last_failure_at: null,
  last_failure_kind: null,
  last_failure_detail: null,
  consecutive_failures: 0,
  items_contributed: 0,
  backoff_until: null,
  ...over,
});

// RTL does not auto-clean in this config, so renders accumulate in document.body
// and a second test finds the first test's DOM as well as its own.
afterEach(cleanup);

describe('DiscoverySources', () => {
  it('a source failing for nineteen days does not look healthy', async () => {
    vi.mocked(healthApi.getDiscoverySources).mockResolvedValue({
      status: 'failing',
      sources: [
        source({
          state: 'failing',
          last_success_at: iso(19),
          last_failure_kind: 'rate_limited',
          consecutive_failures: 19,
        }),
      ],
    });
    renderPanel();

    expect(await screen.findByText('Failing')).toBeTruthy();
    expect(screen.getByText(/19 days ago/)).toBeTruthy();
    expect(screen.getByText(/rate limited/)).toBeTruthy();
    expect(screen.getByText(/19 in a row/)).toBeTruthy();
  });

  it('never succeeded is distinct from found nothing', async () => {
    vi.mocked(healthApi.getDiscoverySources).mockResolvedValue({
      status: 'never_succeeded',
      sources: [source({ state: 'never_succeeded', last_success_at: null })],
    });
    renderPanel();

    expect(await screen.findByText('Never succeeded')).toBeTruthy();
    // The wording is the point: an empty result and a broken source read alike
    // without it, which is how nineteen nights passed unnoticed.
    expect(
      screen.getByText(/not the same as "nothing new"/),
    ).toBeTruthy();
  });

  it('backing off says when it will retry', async () => {
    vi.mocked(healthApi.getDiscoverySources).mockResolvedValue({
      status: 'backing_off',
      sources: [
        source({
          state: 'backing_off',
          last_failure_kind: 'rate_limited',
          consecutive_failures: 2,
          backoff_until: new Date(Date.now() + 240_000).toISOString(),
        }),
      ],
    });
    renderPanel();

    expect(await screen.findByText('Backing off')).toBeTruthy();
    expect(screen.getByText(/retrying in 4 min/)).toBeTruthy();
  });

  it('leads with when a source last found something, not when it last ran', async () => {
    vi.mocked(healthApi.getDiscoverySources).mockResolvedValue({
      status: 'working',
      sources: [source({ items_contributed: 600 })],
    });
    renderPanel();

    expect(await screen.findByText(/Last found something/)).toBeTruthy();
    expect(screen.getByText(/600 releases contributed/)).toBeTruthy();
  });

  it('a failed read renders as an error, not as an empty healthy panel', async () => {
    vi.mocked(healthApi.getDiscoverySources).mockRejectedValue(new Error('nope'));
    renderPanel();

    expect(
      await screen.findByText(/Could not read discovery source health/),
    ).toBeTruthy();
  });
});

describe('DiscoverySources — unmonitored sources', () => {
  it('a source nothing has attempted reads as not monitored, not as broken', async () => {
    vi.mocked(healthApi.getDiscoverySources).mockResolvedValue({
      status: 'working',
      sources: [
        source({ source: 'bandcamp', state: 'not_instrumented', last_success_at: null }),
      ],
    });
    renderPanel();

    expect(await screen.findByText('Not monitored')).toBeTruthy();
    expect(screen.getByText(/not yet reporting health/)).toBeTruthy();
    // The alarming wording belongs to never_succeeded, not to this.
    expect(screen.queryByText(/never found anything/)).toBeNull();
  });
});

describe('DiscoverySources — switched off', () => {
  it('a disabled source reads as off, not as broken or as working', async () => {
    vi.mocked(healthApi.getDiscoverySources).mockResolvedValue({
      status: 'working',
      sources: [source({ state: 'disabled', last_success_at: iso(30) })],
    });
    renderPanel();

    expect(await screen.findByText('Off')).toBeTruthy();
    expect(screen.getByText(/cached results are still served/)).toBeTruthy();
    // It kept a last_success_at from before it was switched off; that must not be
    // what the row leads with, or "off" reads as "fine".
    expect(screen.queryByText(/Last found something/)).toBeNull();
    expect(screen.queryByText('Failing')).toBeNull();
  });
});
