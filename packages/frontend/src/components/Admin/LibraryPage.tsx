/**
 * The Library destination (ADR-0058 point 2) — where the app opens.
 *
 * Dashboard, scan and sync, analysis, artist cleanup. Point 2 also names **pending review**, which
 * is not here: there was a client wrapper with no component behind it, so a row for it would be an
 * affordance whose destination is not mounted. ADR-0077 deleted the wrapper; the gap is still
 * recorded in `UNBUILT_DESTINATION_ITEMS` rather than linked and left to fail silently.
 */
import { Link } from 'react-router-dom';
import { Combine, ChevronRight } from 'lucide-react';

import { AdminPage, AdminSection } from './AdminPage';
import { Dashboard } from './Dashboard';
import { LibrarySync } from '../Settings/LibrarySync';
import { AnalysisSettings } from '../Settings/AnalysisSettings';

export function LibraryPage() {
  return (
    <AdminPage title="Library" subtitle="The state of the collection, and the jobs that build it">
      <Dashboard />

      <AdminSection title="Scan & analysis">
        <LibrarySync />
        <AnalysisSettings />
      </AdminSection>

      <AdminSection title="Maintenance">
        <Link
          to="/library/artist-cleanup"
          aria-label="Artist cleanup"
          className="flex items-center gap-3 bg-zinc-800/50 rounded-lg p-4 hover:bg-zinc-800 transition-colors"
        >
          <Combine className="w-5 h-5 text-cyan-400 flex-shrink-0" />
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium text-white">
              Artist cleanup
            </div>
            <div className="text-sm text-zinc-400">
              Merge duplicate artists and fix name variants
            </div>
          </div>
          <ChevronRight className="w-4 h-4 text-zinc-500 flex-shrink-0" />
        </Link>
      </AdminSection>
    </AdminPage>
  );
}
