/**
 * Whether each discovery source is actually working (ADR-0099 point 6).
 *
 * **Deliberately not the question `ApiKeyStatus` answers.** That panel reports
 * whether a key is *configured*, and a source can hold a valid key, be scheduled,
 * run every night, fail every time, and look identical to a healthy one. That is
 * not hypothetical: the nightly discovery job crashed nineteen nights running,
 * logged at ERROR, and every surface in the app showed green.
 *
 * So the fact this leads with is **when a source last found something** — not when
 * it last ran, which the old dashboard could already imply and which was true
 * throughout the outage.
 */
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle, Clock, HelpCircle, XCircle } from 'lucide-react';
import { healthApi, type DiscoverySourceHealth } from '../../api/admin';
import { queryKeys } from '../../api/queryKeys';

const REFRESH_MS = 30_000;

/** Human labels. The source key is an implementation detail, not a name. */
const SOURCE_LABELS: Record<string, string> = {
  musicbrainz: 'MusicBrainz',
  listenbrainz: 'ListenBrainz',
  lastfm: 'Last.fm',
  bandcamp: 'Bandcamp',
  discovery_batch: 'Discovery job',
};

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

function SourceRow({ source }: { source: DiscoverySourceHealth }) {
  const style = STATE_STYLES[source.state] ?? STATE_STYLES.working;
  const { Icon } = style;
  const lastSuccess = relative(source.last_success_at);
  const retry = untilNow(source.backoff_until);

  return (
    <div className="flex items-start gap-3 p-3 bg-zinc-900/50 rounded-lg">
      <Icon className={`w-5 h-5 flex-shrink-0 mt-0.5 ${style.cls}`} />
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2 flex-wrap">
          <p className="text-sm text-white">{SOURCE_LABELS[source.source] ?? source.source}</p>
          <span className={`text-xs ${style.cls}`}>{style.label}</span>
        </div>

        {/* "Last found something", not "last ran" — the distinction the outage turned on. */}
        <p className="text-xs text-zinc-400 mt-0.5">
          {lastSuccess
            ? `Last found something ${lastSuccess}`
            : source.state === 'not_instrumented'
              ? 'Used for recommendations; not yet reporting health'
              : 'Has never found anything — this is not the same as "nothing new"'}
        </p>

        {source.last_failure_kind && (
          <p className="text-xs text-zinc-500 mt-0.5">
            Last failure: {source.last_failure_kind.replace(/_/g, ' ')}
            {source.consecutive_failures > 1 && ` (${source.consecutive_failures} in a row)`}
            {retry && ` — ${retry}`}
          </p>
        )}

        {source.items_contributed > 0 && (
          <p className="text-xs text-zinc-500 mt-0.5">
            {source.items_contributed.toLocaleString()} releases contributed
          </p>
        )}
      </div>
    </div>
  );
}

export function DiscoverySources() {
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.discoverySources.all,
    queryFn: healthApi.getDiscoverySources,
    refetchInterval: REFRESH_MS,
  });

  if (isLoading) {
    return (
      <div className="bg-zinc-800/50 rounded-lg p-4">
        <div className="animate-pulse h-16 bg-zinc-700/50 rounded" />
      </div>
    );
  }

  // An error here is itself a health signal and must not render as an empty,
  // healthy-looking panel — that is the failure this whole surface exists to stop.
  if (isError || !data) {
    return (
      <div className="bg-zinc-800/50 rounded-lg p-4">
        <p className="text-sm text-danger">Could not read discovery source health.</p>
      </div>
    );
  }

  return (
    <div className="bg-zinc-800/50 rounded-lg p-4 space-y-3">
      <div>
        <h4 className="font-medium text-white">Discovery sources</h4>
        <p className="text-sm text-zinc-400">
          Whether each source is working — not whether a key is configured
        </p>
      </div>

      <div className="space-y-2">
        {data.sources.map((source) => (
          <SourceRow key={source.source} source={source} />
        ))}
      </div>
    </div>
  );
}
