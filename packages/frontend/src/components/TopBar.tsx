/**
 * TopBar — the whole navigation of the administration tool (ADR-0080 point 1).
 *
 * Replaces `Sidebar` (a 240px rail with a collapse control, for three destinations) and
 * `ContentToolbar` (a search box and column chooser that rendered only under `/library/*`, where the
 * one mounted route reads neither, plus the status menu ADR-0080 removes).
 *
 * **One bar at every width**, which is the point: the previous arrangement had a desktop sidebar and
 * a separate mobile bottom bar with its own duplicated destination list, and the mobile half — the
 * one no test opened — is where two dead affordances survived. Three destinations fit across a phone.
 *
 * The links carry `aria-label={item.label}` so their accessible name is exactly the label. The E2E
 * helper matches `getByRole('link', { name: label, exact: true })` and every spec's boot probe waits
 * on those three names (`packages/web/e2e/helpers.ts`), so this is the seam that proves the redesign
 * did not break navigation — keeping it is cheaper than rewriting the tests that would have proved it.
 */
import { useLocation, Link } from 'react-router-dom';
import { House, Wrench, Server } from 'lucide-react';

import { DESTINATIONS } from '../routes';

const DESTINATION_ICONS: Record<string, typeof House> = {
  '/': House,
  '/tools': Wrench,
  '/server': Server,
};

const DESTINATION_ITEMS = DESTINATIONS.map((d) => ({
  ...d,
  icon: DESTINATION_ICONS[d.path] ?? House,
}));

export function TopBar() {
  const location = useLocation();

  /**
   * Library owns the routes it links onward to.
   *
   * `/` is exact — otherwise it matches everything. The `/library/*` pages are reached from the
   * Library and Tools pages rather than from this bar, so they highlight the destination that got
   * you there instead of leaving nothing lit.
   */
  const isActive = (path: string) => {
    if (path === '/') {
      return location.pathname === '/' || location.pathname.startsWith('/library/');
    }
    return location.pathname === path;
  };

  return (
    <header className="shrink-0 border-b border-zinc-800 bg-zinc-950">
      <div className="flex items-center gap-3 px-3 sm:px-4 py-1.5">
        <span className="hidden sm:block text-sm font-semibold text-white pr-1">Familiar</span>

        <nav className="flex items-center gap-1">
          {DESTINATION_ITEMS.map((item) => (
            <Link
              key={item.path}
              to={item.path}
              aria-label={item.label}
              aria-current={isActive(item.path) ? 'page' : undefined}
              title={item.description}
              className={`flex flex-col items-center justify-center gap-0.5 w-20 px-2 py-1.5 rounded-lg transition-colors ${
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
      </div>
    </header>
  );
}
