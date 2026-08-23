/**
 * What is left of Settings after ADR-0058.
 *
 * Nine sections became three. The rest did not disappear — they moved to the destination they
 * belong to (point 2): system, keys, profiles, Last.fm and diagnostics to **Server**; sync,
 * analysis and cleanup to **Library**; backup and community cache to **Tools**.
 *
 * **Four were deleted outright** (point 5): shuffle weights, radio, audio effects and queue sync.
 * They are listener preferences the native clients own per-device under ADR-0029, and they do not
 * configure the fallback player in any useful sense — they configure a listening experience the
 * browser no longer provides.
 *
 * What remains is what point 5's second wave leaves behind. **Theme** outlives the player, because
 * it applies to this administration interface itself. **Playback** and **Offline & Storage** left
 * with the player and the Dexie store (ADR-0071), which is what point 5 said would happen.
 */
import { ThemeSettings } from './ThemeSettings';

export function SettingsPanel() {
  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-medium text-zinc-400 dark:text-zinc-400 light:text-zinc-500 uppercase tracking-wider mb-3">
          Appearance
        </h3>
        <div className="space-y-4">
          <ThemeSettings />
        </div>
      </section>

    </div>
  );
}

export { LastfmSettings } from './LastfmSettings';
export { DataManagement } from './DataManagement';
