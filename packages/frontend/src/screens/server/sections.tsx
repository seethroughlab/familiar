/**
 * Server → its sections (ADR-0126 point 6): the installation, grouped by what an operator is doing.
 *
 * Each is a route of its own under `/server`; `ServerLayout` renders the rail. Small enough to
 * share a file: these compose existing panels, and the composition is the decision.
 */
import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';

import { systemApi } from '../../api';
import { queryKeys } from '../../api/queryKeys';
import { BackgroundJobs } from '../../panels/server/BackgroundJobs';
import { BackupRestore } from '../../panels/server/BackupRestore';
import { BackupSettings } from '../../panels/server/BackupSettings';
import { DebugSettings } from '../../panels/server/DebugSettings';
import { ProfileSettings } from '../../panels/server/ProfileSettings';
import { ProviderCards } from '../../panels/server/ProviderCards';
import { RemoteLogsPanel } from '../../panels/server/RemoteLogsPanel';
import { ServerTokenSettings } from '../../panels/server/ServerTokenSettings';
import { SystemStatus } from '../../panels/server/SystemStatus';
import { DataManagement } from '../../panels/tools/DataManagement';
import { useBackgroundJobsStore } from '../../stores/backgroundJobsStore';
import { SectionPage } from '../AdminPage';

/**
 * The library path, read-only, with the variable named (point 10).
 *
 * Nothing in the web app can set it: `PUT /settings` does not accept it and the settings
 * response drops it. Showing it as a form that cannot save is the thing point 10 forbids;
 * showing where it comes from is the honest version.
 */
function LibraryPath() {
  const health = useQuery({ queryKey: queryKeys.systemHealth.all, queryFn: systemApi.health, staleTime: 30_000 });
  const library = health.data?.services?.find((s) => s.name === 'library');
  const paths = (library?.details?.configured_paths as string[] | undefined) ?? [];
  return (
    <div className="bg-zinc-800/50 rounded-lg p-4 space-y-1">
      <h4 className="font-medium text-white">Library path</h4>
      <p className="text-sm text-zinc-300 font-mono">{paths.length ? paths.join(', ') : '—'}</p>
      <p className="text-xs text-zinc-500">
        Set by <code>MUSIC_LIBRARY_PATH</code> on the server — an environment variable, not editable here.
        {library?.message ? ` ${library.message}.` : ''}
      </p>
    </div>
  );
}

export function HealthSection() {
  return (
    <SectionPage title="Health" subtitle="The services this process depends on, and the version it runs">
      <SystemStatus />
      <LibraryPath />
    </SectionPage>
  );
}

export function JobsSection() {
  // `BackgroundJobs` renders nothing when idle (right on a page that has other things to say);
  // a section of its own has to say "nothing running" out loud.
  const { activeCount, startPolling, stopPolling } = useBackgroundJobsStore();
  useEffect(() => {
    startPolling();
    return () => stopPolling();
  }, [startPolling, stopPolling]);
  return (
    <SectionPage title="Jobs" subtitle="Library sync, artwork fetch and S3 backup while they run">
      {activeCount === 0 ? (
        <p className="text-sm text-zinc-400">Nothing is running.</p>
      ) : (
        <BackgroundJobs />
      )}
    </SectionPage>
  );
}

export function ProvidersSection() {
  return (
    <SectionPage title="Providers" subtitle="One card per provider: its key, its connection, whether it is working, its last run">
      <ProviderCards />
    </SectionPage>
  );
}

export function BackupSection() {
  return (
    <SectionPage title="Backup" subtitle="The installation backup to S3 — database, settings, audio — and restoring from it">
      <BackupSettings />
      <BackupRestore />
    </SectionPage>
  );
}

export function PeopleSection() {
  return (
    <SectionPage title="People" subtitle="Profiles, and moving a profile's listening data to another server">
      <ProfileSettings />
      <DataManagement />
    </SectionPage>
  );
}

export function AccessSection() {
  return (
    <SectionPage title="Access" subtitle="How this client reaches the server">
      {/* No server-URL field: this page is served by the server it administers. The token sits
          here because a wrong token and a wrong URL fail the same way — "nothing loads" — which is
          the argument `ServerTokenSettings` makes for its own placement. */}
      <ServerTokenSettings />
    </SectionPage>
  );
}

export function DiagnosticsSection() {
  // Developer tools are hidden by default. Shown in dev builds, or on any build by setting
  // localStorage 'familiar:devTools' = '1'. Carried over unchanged from the old Server page.
  const showDevTools =
    import.meta.env.DEV ||
    (typeof localStorage !== 'undefined' && localStorage.getItem('familiar:devTools') === '1');
  return (
    <SectionPage title="Diagnostics" subtitle="Console capture and remote logs">
      {showDevTools ? (
        <>
          <DebugSettings />
          <RemoteLogsPanel />
        </>
      ) : (
        <p className="text-sm text-zinc-400">
          Hidden on this build. Set <code>localStorage['familiar:devTools'] = '1'</code> and reload to show
          console capture and remote logs. The diagnostics export is under Health.
        </p>
      )}
    </SectionPage>
  );
}
