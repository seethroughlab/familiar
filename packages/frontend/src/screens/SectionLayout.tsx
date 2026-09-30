/**
 * A destination with local navigation (ADR-0126 point 7).
 *
 * The heading names the destination; the rail lists its sections, each a route of its own, so a
 * section can be linked, reloaded and reached with browser history. On a desktop the rail is a
 * column beside the content; on a phone the same links become a horizontally scrolling row over
 * the same routes — one registry, two arrangements, never a second destination list (the
 * duplicated mobile bottom bar is where two dead affordances once survived unseen).
 *
 * Active state uses `isUnder`, the rule the top bar uses, so `/library/duplicates` lights both
 * Library in the bar and Duplicates in the rail (point 8).
 */
import { NavLink, Outlet, useLocation } from 'react-router-dom';

import { DESTINATIONS, SECTIONS, isUnder, type DestinationPath } from '../app/routes';

export function SectionLayout({ destination }: { destination: Exclude<DestinationPath, '/'> }) {
  const location = useLocation();
  const meta = DESTINATIONS.find((d) => d.path === destination)!;
  const sections = SECTIONS[destination];

  // The index section is `destination` itself; it must not light up under a sibling.
  const isCurrent = (path: string) =>
    path === destination ? location.pathname === destination : isUnder(location.pathname, path);

  return (
    <div className="p-4 sm:p-6 max-w-6xl mx-auto space-y-5">
      <div>
        <h2 className="text-xl font-bold text-white">{meta.label}</h2>
        <p className="text-sm text-zinc-400 mt-1">{meta.description}</p>
      </div>

      <div className="flex flex-col md:flex-row gap-5 md:gap-8">
        <nav
          aria-label={`${meta.label} sections`}
          className="flex md:flex-col gap-1 overflow-x-auto md:overflow-visible md:w-48 md:shrink-0 -mx-4 px-4 md:mx-0 md:px-0"
        >
          {sections.map((section) => {
            const current = isCurrent(section.path);
            return (
              <NavLink
                key={section.path}
                to={section.path}
                end
                aria-current={current ? 'page' : undefined}
                className={`shrink-0 rounded-lg px-3 py-2 text-sm transition-colors ${
                  current
                    ? 'bg-zinc-800 text-white'
                    : 'text-zinc-400 hover:bg-zinc-800/60 hover:text-zinc-200'
                }`}
              >
                {section.label}
              </NavLink>
            );
          })}
        </nav>

        <div className="min-w-0 flex-1">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
