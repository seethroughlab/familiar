/**
 * One card per provider (ADR-0126 point 2): its key, its connection, whether it works, its last run.
 *
 * Until ADR-0126 a provider was four panels in three sections — Last.fm's key status in
 * `ApiKeyStatus` under Access, its connect button in `LastfmSettings` under Integrations, whether
 * it worked in `DiscoverySources` under Discovery, and its nightly run in `BackgroundJobs`. The
 * card puts them together, and shows what none of them could alone: *key set, account not
 * connected, no calls recorded* is one sentence about one provider.
 *
 * The health half keeps `DiscoverySources`' rule (ADR-0099 point 6): **lead with when a source
 * last found something**, not whether a key is configured. A source can hold a valid key, run
 * every night, fail every time and look identical to a healthy one — the nightly discovery job
 * crashed nineteen nights running, logged at ERROR, and every surface showed green. The tests
 * that pinned that behaviour moved here with the code.
 */
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle, Clock, HelpCircle, PowerOff, XCircle } from 'lucide-react';
import type { ReactNode } from 'react';

import { appSettingsApi, systemApi, type DiscoverySourceHealth } from '../../api';
import { queryKeys } from '../../api/queryKeys';
import { LastfmSettings } from './LastfmSettings';
import { SoulseekSettings } from './SoulseekSettings';

const REFRESH_MS = 30_000;

/** Human labels. The source key is an implementation detail, not a name. */
const SOURCE_LABELS: Record<string, string> = {
  musicbrainz: 'MusicBrainz',
  listenbrainz: 'ListenBrainz',
  lastfm: 'Last.fm',
  acoustid: 'AcoustID',
  bandcamp: 'Bandcamp',
  soulseek: 'Soulseek',
  community_cache_claims: 'Community cache',
  discovery_batch: 'Nightly discovery',
};

/**
 * The providers, in card order, with what each needs from the operator (ADR-0126 point 6).
 *
 * Keys are environment variables the web app cannot set — `ApiKeyStatus` said "Configured via
 * environment variables" under a heading that implied otherwise. The card names the variable.
 * `community_cache_claims` is not here: the cache is the analysis pipeline's concern and sits
 * with its toggles under Analysis → Configuration (point 5).
 */
const PROVIDERS: readonly {
  source: string;
  key: { env: string; configuredFlag: 'lastfm_configured' | 'acoustid_configured' } | 'none';
  panel?: ReactNode;
  note?: string;
}[] = [
  { source: 'lastfm', key: { env: 'LASTFM_API_KEY', configuredFlag: 'lastfm_configured' }, panel: <LastfmSettings /> },
  { source: 'musicbrainz', key: 'none' },
  { source: 'acoustid', key: { env: 'ACOUSTID_API_KEY', configuredFlag: 'acoustid_configured' }, note: 'Names recordings during analysis; the toggle is under Analysis → Configuration.' },
  { source: 'listenbrainz', key: 'none' },
  { source: 'bandcamp', key: 'none' },
  { source: 'soulseek', key: 'none', panel: <SoulseekSettings />, note: 'The four Soulseek tools are withheld from MCP hosts until a slskd address is saved below.' },
];

const STATE_STYLES: Record<string, { label: string; cls: string; Icon: typeof CheckCircle }> = {
  working: { label: 'Working', cls: 'text-success', Icon: CheckCircle },
  degraded: { label: 'Degraded', cls: 'text-warning', Icon: AlertTriangle },
  backing_off: { label: 'Backing off', cls: 'text-warning', Icon: Clock },
  failing: { label: 'Failing', cls: 'text-danger', Icon: XCircle },
  never_succeeded: { label: 'Never succeeded', cls: 'text-danger', Icon: HelpCircle },
  // Nothing has attempted this source yet — unmonitored, not broken. Neutral on
  // purpose: colouring it would make the panel cry wolf about a source that is
  // simply not wired to the recorder until ADR-0099 point 5.
  not_instrumented: { label: 'Not monitored', cls: 'text-zinc-500', Icon: HelpCircle },
  // Switched off by the owner. Neutral, and distinct from every failure state: "off"
  // must not look like "broken", which is the confusion this panel exists to remove.
  disabled: { label: 'Off', cls: 'text-zinc-500', Icon: PowerOff },
};

function relative(iso: string | null): string | null {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return null;
  const mins = Math.max(0, Math.round((Date.now() - then) / 60_000));
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`;
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? '' : 's'} ago`;
}

function untilNow(iso: string | null): string | null {
  if (!iso) return null;
  const mins = Math.round((new Date(iso).getTime() - Date.now()) / 60_000);
  if (Number.isNaN(mins) || mins <= 0) return null;
  return mins < 60 ? `retrying in ${mins} min` : `retrying in ${Math.round(mins / 60)} h`;
}

/** A provider's health, in the words `DiscoverySources` chose: found something, not ran. */
export function SourceHealth({ source, showName = true }: { source: DiscoverySourceHealth; showName?: boolean }) {
  const style = STATE_STYLES[source.state] ?? STATE_STYLES.working;
  const { Icon } = style;
  const lastSuccess = relative(source.last_success_at ?? null);
  const retry = untilNow(source.backoff_until ?? null);

  return (
    <div className="flex items-start gap-3">
      <Icon className={`w-5 h-5 flex-shrink-0 mt-0.5 ${style.cls}`} />
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2 flex-wrap">
          {showName && <p className="text-sm text-white">{SOURCE_LABELS[source.source] ?? source.source}</p>}
          <span className={`text-xs ${style.cls}`}>{style.label}</span>
        </div>

        {/* "Last found something", not "last ran" — the distinction the outage turned on. */}
        <p className="text-xs text-zinc-400 mt-0.5">
          {source.state === 'disabled'
            ? 'Turned off in settings; cached results are still served'
            : lastSuccess
            ? `Last found something ${lastSuccess}`
            : source.state === 'not_instrumented'
              ? 'Used for recommendations; not yet reporting health'
              : 'Has never found anything — this is not the same as "nothing new"'}
        </p>

        {source.last_failure_kind && (
          <p className="text-xs text-zinc-500 mt-0.5">
            Last failure: {source.last_failure_kind.replace(/_/g, ' ')}
            {(source.consecutive_failures ?? 0) > 1 && ` (${source.consecutive_failures} in a row)`}
            {retry && ` — ${retry}`}
          </p>
        )}

        {(source.items_contributed ?? 0) > 0 && (
          <p className="text-xs text-zinc-500 mt-0.5">
            {(source.items_contributed ?? 0).toLocaleString()} releases contributed
          </p>
        )}
      </div>
    </div>
  );
}

/** The one line the old `ApiKeyStatus` panel had per service, now on the provider it belongs to. */
function KeyLine({ env, configured }: { env: string; configured: boolean | undefined }) {
  return (
    <p className="text-xs text-zinc-400">
      Key {configured ? 'set' : 'not set'} · <code className="text-zinc-500">{env}</code>
      <span className="text-zinc-500"> — an environment variable; not editable here</span>
    </p>
  );
}

export function ProviderCards() {
  const health = useQuery({
    queryKey: queryKeys.discoverySources.all,
    queryFn: systemApi.discoverySources,
    refetchInterval: REFRESH_MS,
  });
  const settings = useQuery({ queryKey: queryKeys.appSettings.all, queryFn: appSettingsApi.get });

  if (health.isLoading) {
    return (
      <div className="bg-zinc-800/50 rounded-lg p-4">
        <div className="animate-pulse h-16 bg-zinc-700/50 rounded" />
      </div>
    );
  }

  // An error here is itself a health signal and must not render as an empty,
  // healthy-looking panel — that is the failure this whole surface exists to stop.
  if (health.isError || !health.data) {
    return (
      <div className="bg-zinc-800/50 rounded-lg p-4">
        <p className="text-sm text-danger">Could not read provider health.</p>
      </div>
    );
  }

  const bySource = new Map(health.data.sources.map((s) => [s.source, s]));
  const batch = bySource.get('discovery_batch');

  return (
    <div className="space-y-3">
      {/* The job that drives the discovery providers: one line, because it is not a provider and
          because whether it ran is the first thing to know when every provider looks quiet. */}
      {batch && (
        <div className="bg-zinc-800/50 rounded-lg p-3">
          <SourceHealth source={batch} />
        </div>
      )}

      {PROVIDERS.map((provider) => {
        const source = bySource.get(provider.source);
        const label = SOURCE_LABELS[provider.source] ?? provider.source;
        return (
          <section key={provider.source} aria-label={label} className="bg-zinc-800/50 rounded-lg p-4 space-y-3">
            <h4 className="font-medium text-white">{label}</h4>

            {source ? (
              <SourceHealth source={source} showName={false} />
            ) : (
              <p className="text-xs text-zinc-500">No health recorded for this provider.</p>
            )}

            {provider.key !== 'none' ? (
              <KeyLine env={provider.key.env} configured={settings.data?.[provider.key.configuredFlag]} />
            ) : provider.source !== 'soulseek' ? (
              <p className="text-xs text-zinc-500">No key needed.</p>
            ) : null}

            {provider.note && <p className="text-xs text-zinc-500">{provider.note}</p>}

            {provider.panel}
          </section>
        );
      })}
    </div>
  );
}
