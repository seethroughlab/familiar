/**
 * The Tools destination (ADR-0058 point 2) — things you run against the library.
 *
 * Duplicates, organiser, artwork, backup and restore, and the community cache. Duplicates and the
 * organiser are both **preview-only, because the server has no apply route for either**.
 *
 * The fallback player's "Track list" link left with the player itself — ADR-0057 point 5, a
 * capability and its affordances leave together.
 */
import { Link } from 'react-router-dom';
import { Copy, FolderTree, Image, ChevronRight } from 'lucide-react';

import { AdminPage, AdminSection } from './AdminPage';
import { DataManagement } from '../Settings/DataManagement';
import { CommunityCache } from '../Settings/CommunityCache';

export function ToolsPage() {
  return (
    <AdminPage title="Tools" subtitle="Jobs and utilities you run against the library">
      <AdminSection title="Inspect">
        <ToolLink
          to="/tools/duplicates"
          icon={<Copy className="w-5 h-5 text-cyan-400 flex-shrink-0" />}
          label="Duplicates"
          description="Find tracks that appear more than once, and which copy is better"
        />
        <ToolLink
          to="/tools/artwork"
          icon={<Image className="w-5 h-5 text-cyan-400 flex-shrink-0" />}
          label="Cover art"
          description="See what has real artwork, and re-fetch placeholders"
        />
        <ToolLink
          to="/tools/organize"
          icon={<FolderTree className="w-5 h-5 text-cyan-400 flex-shrink-0" />}
          label="Organiser"
          description="See where files would move under a naming template"
        />
      </AdminSection>

      <AdminSection title="Data">
        <DataManagement />
        <CommunityCache />
      </AdminSection>

    </AdminPage>
  );
}

function ToolLink({
  to,
  icon,
  label,
  description,
}: {
  to: string;
  icon: React.ReactNode;
  label: string;
  description: string;
}) {
  return (
    <Link
      to={to}
      // The label is the name; the description is a hint beneath it. Without this the accessible
      // name is the whole card — which is what a screen reader announces, and what the E2E
      // navigation helpers have to match. See the sidebar for the same reasoning.
      aria-label={label}
      className="flex items-center gap-3 bg-zinc-800/50 dark:bg-zinc-800/50 light:bg-zinc-100 rounded-lg p-4 hover:bg-zinc-800 transition-colors"
    >
      {icon}
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium text-white dark:text-white light:text-zinc-900">
          {label}
        </div>
        <div className="text-sm text-zinc-400 dark:text-zinc-400 light:text-zinc-600">
          {description}
        </div>
      </div>
      <ChevronRight className="w-4 h-4 text-zinc-500 flex-shrink-0" />
    </Link>
  );
}
