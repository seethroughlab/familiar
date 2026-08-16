/**
 * The Tools destination (ADR-0058 point 2) — things you run against the library.
 *
 * Backup and restore, community cache, and the fallback player. Point 2 also names **duplicates**
 * and the **organiser**; both are phase 4 and neither has a UI yet, so neither is linked. See
 * `UNBUILT_DESTINATION_ITEMS`.
 */
import { Link } from 'react-router-dom';
import { List, ChevronRight } from 'lucide-react';

import { AdminPage, AdminSection } from './AdminPage';
import { DataManagement } from '../Settings/DataManagement';
import { CommunityCache } from '../Settings/CommunityCache';

export function ToolsPage() {
  return (
    <AdminPage title="Tools" subtitle="Jobs and utilities you run against the library">
      <AdminSection title="Data">
        <DataManagement />
        <CommunityCache />
      </AdminSection>

      {/*
        * The fallback player lives here rather than in the sidebar (ADR-0058 point 3). It is a
        * stop-gap for a guest machine, scheduled for deletion when `docs/WEB-PARITY.md` shows no ❌
        * in the Mac and iPhone columns of its Listening table (point 4) — and a top-level
        * destination is not what you give something on the way out. No redesign, no new controls.
        */}
      <AdminSection title="Playback">
        <Link
          to="/library/tracks"
          className="flex items-center gap-3 bg-zinc-800/50 dark:bg-zinc-800/50 light:bg-zinc-100 rounded-lg p-4 hover:bg-zinc-800 transition-colors"
        >
          <List className="w-5 h-5 text-cyan-400 flex-shrink-0" />
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium text-white dark:text-white light:text-zinc-900">
              Track list
            </div>
            <div className="text-sm text-zinc-400 dark:text-zinc-400 light:text-zinc-600">
              Search the library and play something in this browser
            </div>
          </div>
          <ChevronRight className="w-4 h-4 text-zinc-500 flex-shrink-0" />
        </Link>
      </AdminSection>
    </AdminPage>
  );
}
