import { SpotifySettings } from './SpotifySettings';
import { LastfmSettings } from './LastfmSettings';
import { OfflineSettings } from './OfflineSettings';
import { ThemeSettings } from './ThemeSettings';
import { PlaybackSettings } from './PlaybackSettings';
import { AudioEffectsSettings } from './AudioEffectsSettings';
import { ProfileSettings } from './ProfileSettings';
import { SystemStatus } from './SystemStatus';
import { LibrarySync } from './LibrarySync';
import { MetadataSettings } from './MetadataSettings';
import { AnalysisSettings } from './AnalysisSettings';
import { PluginsSettings } from './PluginsSettings';
import { InstallStatus } from '../PWA/InstallPrompt';
import { DebugSettings } from './DebugSettings';
import { AISettings } from './AISettings';
import { DataManagement } from './DataManagement';
import { SubsonicSettings } from './SubsonicSettings';

export function SettingsPanel() {
  return (
    <div className="p-6 space-y-6">
      <div>
        <h2 className="text-xl font-bold text-white dark:text-white light:text-zinc-900 mb-2">Settings</h2>
        <p className="text-sm text-zinc-400 dark:text-zinc-400 light:text-zinc-600">Manage your integrations and preferences</p>
      </div>

      <div className="space-y-6">
        {/* System Status at the top for visibility */}
        <section>
          <h3 className="text-sm font-medium text-zinc-400 dark:text-zinc-400 light:text-zinc-500 uppercase tracking-wider mb-3">
            System
          </h3>
          <div className="space-y-4">
            <SystemStatus />
          </div>
        </section>

        <section>
          <h3 className="text-sm font-medium text-zinc-400 dark:text-zinc-400 light:text-zinc-500 uppercase tracking-wider mb-3">
            Library
          </h3>
          <div className="space-y-4">
            <LibrarySync />
            <MetadataSettings />
            <AnalysisSettings />
          </div>
        </section>

        <section>
          <h3 className="text-sm font-medium text-zinc-400 dark:text-zinc-400 light:text-zinc-500 uppercase tracking-wider mb-3">
            AI Assistant
          </h3>
          <div className="space-y-4">
            <AISettings />
          </div>
        </section>

        <section>
          <h3 className="text-sm font-medium text-zinc-400 dark:text-zinc-400 light:text-zinc-500 uppercase tracking-wider mb-3">
            Profile
          </h3>
          <div className="space-y-4">
            <ProfileSettings />
          </div>
        </section>

        <section>
          <h3 className="text-sm font-medium text-zinc-400 dark:text-zinc-400 light:text-zinc-500 uppercase tracking-wider mb-3">
            App
          </h3>
          <div className="space-y-4">
            <InstallStatus />
          </div>
        </section>

        <section>
          <h3 className="text-sm font-medium text-zinc-400 dark:text-zinc-400 light:text-zinc-500 uppercase tracking-wider mb-3">
            Plugins
          </h3>
          <div className="space-y-4">
            <PluginsSettings />
          </div>
        </section>

        <section>
          <h3 className="text-sm font-medium text-zinc-400 dark:text-zinc-400 light:text-zinc-500 uppercase tracking-wider mb-3">
            Appearance
          </h3>
          <div className="space-y-4">
            <ThemeSettings />
          </div>
        </section>

        <section>
          <h3 className="text-sm font-medium text-zinc-400 dark:text-zinc-400 light:text-zinc-500 uppercase tracking-wider mb-3">
            Playback
          </h3>
          <div className="space-y-4">
            <PlaybackSettings />
            <AudioEffectsSettings />
          </div>
        </section>

        <section>
          <h3 className="text-sm font-medium text-zinc-400 dark:text-zinc-400 light:text-zinc-500 uppercase tracking-wider mb-3">
            Integrations
          </h3>
          <div className="space-y-4">
            <SpotifySettings />
            <LastfmSettings />
            <SubsonicSettings />
          </div>
        </section>

        <section>
          <h3 className="text-sm font-medium text-zinc-400 dark:text-zinc-400 light:text-zinc-500 uppercase tracking-wider mb-3">
            Offline & Storage
          </h3>
          <div className="space-y-4">
            <OfflineSettings />
          </div>
        </section>

        <section>
          <h3 className="text-sm font-medium text-zinc-400 dark:text-zinc-400 light:text-zinc-500 uppercase tracking-wider mb-3">
            Data
          </h3>
          <div className="space-y-4">
            <DataManagement />
          </div>
        </section>

        <section>
          <h3 className="text-sm font-medium text-zinc-400 dark:text-zinc-400 light:text-zinc-500 uppercase tracking-wider mb-3">
            Developer
          </h3>
          <div className="space-y-4">
            <DebugSettings />
          </div>
        </section>

      </div>
    </div>
  );
}

export { SpotifySettings } from './SpotifySettings';
export { LastfmSettings } from './LastfmSettings';
export { OfflineSettings } from './OfflineSettings';
export { DataManagement } from './DataManagement';
