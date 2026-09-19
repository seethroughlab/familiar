/**
 * Shared chrome for the three destinations (ADR-0058 point 2).
 *
 * The settings page these pages replace was one scroll of nine `<section>`s, each hand-rolling the
 * same heading markup with the same four theme classes. Three pages repeating that a third time is
 * how the classes drift apart, so the chrome lives here and the pages carry only content.
 */
import type { ReactNode } from 'react';

export function AdminPage({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <div className="p-4 sm:p-6 max-w-4xl mx-auto space-y-6">
      <div>
        <h2 className="text-xl font-bold text-white">{title}</h2>
        {subtitle && (
          <p className="text-sm text-zinc-400 mt-1">
            {subtitle}
          </p>
        )}
      </div>
      {children}
    </div>
  );
}

export function AdminSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h3 className="text-sm font-medium text-zinc-400 uppercase tracking-wider mb-3">
        {title}
      </h3>
      <div className="space-y-4">{children}</div>
    </section>
  );
}


/**
 * A section inside a destination (ADR-0126 point 7).
 *
 * `SectionLayout` below owns the destination's heading and rail; a section owns only its own
 * title and content. Rendered as an `<h3>` so the destination stays the page's one `<h2>` — the
 * E2E boot probe and the screenshots wait on that heading by name.
 */
export function SectionPage({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold text-white">{title}</h3>
        {subtitle && <p className="text-sm text-zinc-400 mt-1">{subtitle}</p>}
      </div>
      {children}
    </div>
  );
}

