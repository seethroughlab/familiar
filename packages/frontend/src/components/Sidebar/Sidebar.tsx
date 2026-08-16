/**
 * Sidebar — the three destinations of the administration tool (ADR-0058 point 2).
 *
 * It used to list library browsers, then a Collections section with counts, playlists, smart
 * playlists, and right-click context menus on all of them. What was left after the ADR-0057 strip
 * was a music player's navigation with most of its destinations gone — and **three affordances that
 * led nowhere**, all found while rewriting this file:
 *
 * - `/favorites` and `/downloads` had no routes in `App.tsx`. Clicking them hit the catch-all and
 *   silently redirected home.
 * - The mixtape export modal's only `setMixtapeSource` call was its own `onClose`, so nothing could
 *   ever open it.
 *
 * That is the same defect as `familiar` #70, #74 and #76, three more times, in the one component
 * whose entire job is going somewhere. `navigationIntegrity.test.ts` now asserts every destination
 * has a route, which is the guard that would have caught it.
 */
import { useLocation, Link, useNavigate } from 'react-router-dom';
import { House, Wrench, Server, Settings, PanelLeftClose, PanelLeft } from 'lucide-react';
import { useUIStore } from '../../stores/uiStore';
import { useThemeStore } from '../../stores/themeStore';

import { DESTINATIONS } from '../../routes';

const DESTINATION_ICONS: Record<string, typeof House> = {
  '/': House,
  '/tools': Wrench,
  '/server': Server,
};

const DESTINATION_ITEMS = DESTINATIONS.map((d) => ({
  ...d,
  icon: DESTINATION_ICONS[d.path] ?? House,
}));

export function Sidebar() {
  const location = useLocation();
  const navigate = useNavigate();
  const resolvedTheme = useThemeStore((s) => s.resolvedTheme);
  const sidebarCollapsed = useUIStore((s) => s.sidebarCollapsed);
  const setSidebarCollapsed = useUIStore((s) => s.setSidebarCollapsed);

  /**
   * Library owns the routes it links onward to.
   *
   * `/` is exact — otherwise it matches everything. The two `/library/*` pages are reached from
   * the Library and Tools pages rather than the sidebar (point 3), so they highlight the
   * destination that got you there instead of leaving nothing lit.
   */
  const isActive = (path: string) => {
    if (path === '/') {
      return location.pathname === '/' || location.pathname.startsWith('/library/');
    }
    return location.pathname === path;
  };

  const light = resolvedTheme === 'light';
  const bgClass = light ? 'bg-zinc-50 border-zinc-200' : 'bg-zinc-950 border-zinc-800';
  const hoverClass = light ? 'hover:bg-zinc-100' : 'hover:bg-zinc-800';
  const activeClass = light ? 'bg-zinc-200 text-zinc-900' : 'bg-zinc-800 text-white';
  const textClass = light ? 'text-zinc-600' : 'text-zinc-400';
  const dividerClass = light ? 'border-zinc-200' : 'border-zinc-800';

  // Collapsed sidebar (icon-only)
  if (sidebarCollapsed) {
    return (
      <div className={`w-14 flex flex-col border-r ${bgClass} h-full`}>
        <div className="flex-1 py-2 space-y-0.5 overflow-y-auto">
          {DESTINATION_ITEMS.map((item) => (
            <Link
              key={item.path}
              to={item.path}
              className={`flex items-center justify-center mx-1 p-2 rounded-lg transition-colors ${
                isActive(item.path) ? activeClass : `${textClass} ${hoverClass}`
              }`}
              title={item.label}
            >
              <item.icon className="w-5 h-5" />
            </Link>
          ))}
        </div>
        <div className={`border-t p-1 space-y-0.5 ${dividerClass}`}>
          <button
            onClick={() => navigate('/settings')}
            className={`flex items-center justify-center w-full p-2 rounded-lg ${textClass} ${hoverClass}`}
            title="Settings"
          >
            <Settings className="w-5 h-5" />
          </button>
          <button
            onClick={() => setSidebarCollapsed(false)}
            className={`flex items-center justify-center w-full p-2 rounded-lg ${textClass} ${hoverClass}`}
            title="Expand sidebar"
          >
            <PanelLeft className="w-5 h-5" />
          </button>
        </div>
      </div>
    );
  }

  // Expanded sidebar
  return (
    <div className={`w-60 flex flex-col border-r ${bgClass} h-full`}>
      <div className="flex-1 overflow-y-auto min-h-0 py-2">
        <nav className="space-y-0.5 px-2">
          {DESTINATION_ITEMS.map((item) => (
            <Link
              key={item.path}
              to={item.path}
              className={`flex items-start gap-3 px-2 py-2 rounded-lg text-sm transition-colors ${
                isActive(item.path) ? activeClass : `${textClass} ${hoverClass}`
              }`}
            >
              <item.icon className="w-4 h-4 flex-shrink-0 mt-0.5" />
              <span className="min-w-0 flex-1">
                <span className="block truncate">{item.label}</span>
                <span
                  className={`block truncate text-xs ${light ? 'text-zinc-400' : 'text-zinc-500'}`}
                >
                  {item.description}
                </span>
              </span>
            </Link>
          ))}
        </nav>
      </div>

      {/* Footer */}
      <div className={`border-t p-2 ${dividerClass}`}>
        <div className="space-y-0.5">
          <button
            onClick={() => navigate('/settings')}
            className={`flex items-center gap-3 w-full px-2 py-1.5 rounded-lg text-sm transition-colors ${textClass} ${hoverClass}`}
          >
            <Settings className="w-4 h-4" />
            <span>Settings</span>
          </button>
          <button
            onClick={() => setSidebarCollapsed(true)}
            className={`flex items-center gap-3 w-full px-2 py-1.5 rounded-lg text-sm transition-colors ${textClass} ${hoverClass}`}
          >
            <PanelLeftClose className="w-4 h-4" />
            <span>Collapse</span>
          </button>
        </div>
      </div>
    </div>
  );
}
