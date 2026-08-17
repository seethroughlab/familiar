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
import { ServerSettings } from '../Settings/ServerSettings';
import { ServerTokenSettings } from '../Settings/ServerTokenSettings';
import { ProfileSettings } from '../Settings/ProfileSettings';
import { LastfmSettings } from '../Settings/LastfmSettings';
import { DebugSettings } from '../Settings/DebugSettings';
import { RemoteLogsPanel } from '../Settings/RemoteLogsPanel';
import { isNativeApp } from '../../utils/platform';

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

      <AdminSection title="Access">
        <ApiKeyStatus />
        {isNativeApp() && <ServerSettings />}
        {/* Unlike ServerSettings, this is not native-only: the web app is same-origin and so
            needs no URL, but it still has to present a token once the server has one. */}
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
