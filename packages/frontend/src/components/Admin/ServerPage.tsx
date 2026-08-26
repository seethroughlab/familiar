/**
 * The Server destination (ADR-0058 point 2) — the machine under the library.
 *
 * Health, diagnostics, profiles, Last.fm, API keys. These are ADR-0057 point 2's "infrastructural"
 * exception: things done to the *server* rather than to someone's listening, which stay in the
 * browser regardless of what the native clients gain.
 *
 * ADR-0058 point 2 also named an **update channel** for this destination. The only thing that ever
 * filled that slot was `InstallStatus` — PWA install state, not an update channel — and ADR-0059
 * retired it with the rest of the PWA. Recorded in `UNBUILT_DESTINATION_ITEMS` rather than left as
 * an empty section.
 */
import { AdminPage, AdminSection } from './AdminPage';
import { SystemStatus } from '../Settings/SystemStatus';
import { ApiKeyStatus } from '../Settings/ApiKeyStatus';
import { ServerTokenSettings } from '../Settings/ServerTokenSettings';
import { ProfileSettings } from '../Settings/ProfileSettings';
import { LastfmSettings } from '../Settings/LastfmSettings';
import { DebugSettings } from '../Settings/DebugSettings';
import { RemoteLogsPanel } from '../Settings/RemoteLogsPanel';
import { BackgroundJobs } from '../Settings/BackgroundJobs';

export function ServerPage() {
  // Developer tools are hidden by default. Shown in dev builds, or on any build by setting
  // localStorage 'familiar:devTools' = '1'. Carried over from the settings page unchanged.
  const showDevTools =
    import.meta.env.DEV ||
    (typeof localStorage !== 'undefined' && localStorage.getItem('familiar:devTools') === '1');

  return (
    <AdminPage title="Server" subtitle="Health, access and the machine underneath">
      <AdminSection title="Health">
        <SystemStatus />
      </AdminSection>

      {/* Absent unless something is running. Inherited from the status menu ADR-0080 removed —
          `artwork_fetch` and `s3_backup` report their progress nowhere else. */}
      <AdminSection title="Jobs">
        <BackgroundJobs />
      </AdminSection>

      <AdminSection title="Access">
        <ApiKeyStatus />
        {/* No server-URL field: this page is served by the server it administers. The one that
            was here rendered only when `isNativeApp()` was true, which has been false since the
            Capacitor app was deleted (ADR-0001 point 6). The token is a different matter — a
            same-origin app still has to present one once the server has one (ADR-0045). */}
        <ServerTokenSettings />
      </AdminSection>

      <AdminSection title="Profiles">
        <ProfileSettings />
      </AdminSection>

      <AdminSection title="Integrations">
        <LastfmSettings />
      </AdminSection>

      {showDevTools && (
        <AdminSection title="Diagnostics">
          <DebugSettings />
          <RemoteLogsPanel />
        </AdminSection>
      )}
    </AdminPage>
  );
}
