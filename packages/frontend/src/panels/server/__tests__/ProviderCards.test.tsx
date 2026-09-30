/**
 * The acceptance criterion, in ADR-0099's own terms: a source with a valid key
 * that has failed for nineteen days must not look like a working one.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ProviderCards } from '../ProviderCards';
import { systemApi } from '../../../api';

vi.mock('../../../api', () => ({
  systemApi: { discoverySources: vi.fn() },
  appSettingsApi: { get: vi.fn(async () => ({ lastfm_configured: true, acoustid_configured: false })) },
}));
// The cards embed each provider's own management panel; those are tested on their own.
vi.mock('../LastfmSettings', () => ({ LastfmSettings: () => null }));
vi.mock('../SoulseekSettings', () => ({ SoulseekSettings: () => null }));

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ProviderCards />
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

describe('ProviderCards — health', () => {
  it('a source failing for nineteen days does not look healthy', async () => {
    vi.mocked(systemApi.discoverySources).mockResolvedValue({
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
    vi.mocked(systemApi.discoverySources).mockResolvedValue({
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
    vi.mocked(systemApi.discoverySources).mockResolvedValue({
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
    vi.mocked(systemApi.discoverySources).mockResolvedValue({
      status: 'working',
      sources: [source({ items_contributed: 600 })],
    });
    renderPanel();

    expect(await screen.findByText(/Last found something/)).toBeTruthy();
    expect(screen.getByText(/600 releases contributed/)).toBeTruthy();
  });

  it('a failed read renders as an error, not as an empty healthy panel', async () => {
    vi.mocked(systemApi.discoverySources).mockRejectedValue(new Error('nope'));
    renderPanel();

    expect(
      await screen.findByText(/Could not read provider health/),
    ).toBeTruthy();
  });
});

describe('ProviderCards — unmonitored sources', () => {
  it('a source nothing has attempted reads as not monitored, not as broken', async () => {
    vi.mocked(systemApi.discoverySources).mockResolvedValue({
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

describe('ProviderCards — switched off', () => {
  it('a disabled source reads as off, not as broken or as working', async () => {
    vi.mocked(systemApi.discoverySources).mockResolvedValue({
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

describe('ProviderCards — a provider is one card (ADR-0126 point 2)', () => {
  it('shows the key, whether it is set, and that it is not editable here, beside the health', async () => {
    vi.mocked(systemApi.discoverySources).mockResolvedValue({
      status: 'working',
      sources: [source({ source: 'lastfm', state: 'not_instrumented', last_success_at: null })],
    });
    renderPanel();

    const card = await screen.findByRole('region', { name: 'Last.fm' });
    expect(card.textContent).toMatch(/Not monitored/);
    expect(card.textContent).toMatch(/Key set/);
    expect(card.textContent).toMatch(/LASTFM_API_KEY/);
    expect(card.textContent).toMatch(/not editable here/);
  });

  it('a provider with no key says so rather than showing a key line', async () => {
    vi.mocked(systemApi.discoverySources).mockResolvedValue({ status: 'working', sources: [source()] });
    renderPanel();
    const card = await screen.findByRole('region', { name: 'MusicBrainz' });
    expect(card.textContent).toMatch(/No key needed/);
    expect(card.textContent).not.toMatch(/_API_KEY/);
  });

  it('the nightly discovery job is a line above the cards, not a card', async () => {
    vi.mocked(systemApi.discoverySources).mockResolvedValue({
      status: 'working',
      sources: [source({ source: 'discovery_batch', last_failure_kind: 'crashed' })],
    });
    renderPanel();
    expect(await screen.findByText('Nightly discovery')).toBeTruthy();
    expect(screen.queryByRole('region', { name: 'Nightly discovery' })).toBeNull();
  });
});

