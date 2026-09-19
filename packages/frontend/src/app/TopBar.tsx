/**
 * TopBar — the whole navigation of the administration tool (ADR-0080 point 1, ADR-0126 point 1).
 *
 * Replaces `Sidebar` (a 240px rail with a collapse control, for three destinations) and
 * `ContentToolbar` (a search box and column chooser that rendered only under `/library/*`, where the
 * one mounted route reads neither, plus the status menu ADR-0080 removes).
 *
 * **One bar at every width**, which is the point: the previous arrangement had a desktop sidebar and
 * a separate mobile bottom bar with its own duplicated destination list, and the mobile half — the
 * one no test opened — is where two dead affordances survived. Four destinations fit across a phone at 390px — checked on the ADR-0126 review mock.
 *
 * The links carry `aria-label={item.label}` so their accessible name is exactly the label. The E2E
 * helper matches `getByRole('link', { name: label, exact: true })` and every spec's boot probe waits
 * on those four names (`packages/web/e2e/helpers.ts`), so this is the seam that proves the redesign
 * did not break navigation — keeping it is cheaper than rewriting the tests that would have proved it.
 */
import { useLocation, Link } from 'react-router-dom';
import { Gauge, Library, Activity, Server } from 'lucide-react';

import { DESTINATIONS, isUnder } from './routes';

const DESTINATION_ICONS: Record<string, typeof Gauge> = {
  '/': Gauge,
  '/library': Library,
  '/analysis': Activity,
  '/server': Server,
};

const DESTINATION_ITEMS = DESTINATIONS.map((d) => ({
  ...d,
  icon: DESTINATION_ICONS[d.path] ?? Gauge,
}));

export function TopBar() {
  const location = useLocation();

  /**
   * Ancestor matching (ADR-0126 point 8): `/server/providers` lights Server. `isUnder` is the one
   * rule, shared with the section rails — the previous bar had an ancestor rule for Library alone
   * and exact equality for the rest, so Tools went dark on every tool child route.
   */
  const isActive = (path: string) => isUnder(location.pathname, path);

  return (
    <header className="shrink-0 border-b border-zinc-800 bg-zinc-950">
      {/* Three columns so the destinations sit in the centre of the window, the way a Mac
          settings pane arranges its panes — not packed against the left edge after the wordmark.
          The empty third column is what does it: `1fr` on both sides means the middle is centred
          on the *window*, not on the space left over after the brand. Dropping it and using
          `justify-between` would centre the nav between the brand and the right edge, which drifts
          as the wordmark shows and hides at the `sm` breakpoint. */}
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3 px-3 sm:px-4 py-1.5">
        <span className="hidden sm:block text-sm font-semibold text-white justify-self-start">Familiar</span>
        {/* Holds the first column open on small screens, where the wordmark is hidden. */}
        <span className="sm:hidden" aria-hidden="true" />

        <nav className="flex items-center justify-center gap-1">
          {DESTINATION_ITEMS.map((item) => (
            <Link
              key={item.path}
              to={item.path}
              aria-label={item.label}
              aria-current={isActive(item.path) ? 'page' : undefined}
              title={item.description}
              className={`flex flex-col items-center justify-center gap-0.5 w-[4.5rem] sm:w-20 px-1.5 sm:px-2 py-1.5 rounded-lg transition-colors ${
                isActive(item.path)
                  ? 'bg-zinc-800 text-white'
                  : 'text-zinc-400 hover:bg-zinc-800/60 hover:text-zinc-200'
              }`}
            >
              <item.icon className="w-5 h-5" />
              <span className="text-[11px] font-medium leading-none">{item.label}</span>
            </Link>
          ))}
        </nav>

        {/* Balances the brand column. Empty on purpose: the centring is the point, and anything
            put here has to be weighed against pushing the destinations off-centre. */}
        <span aria-hidden="true" />
      </div>
    </header>
  );
}
