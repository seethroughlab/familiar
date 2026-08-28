/**
 * File organiser (ADR-0058 phase 4) — preview only.
 *
 * `organizerApi` has existed with all three methods and **has never been called from anywhere**.
 * That is the fourth generated-and-uncalled capability this ADR has turned up: `libraryApi.getStats`,
 * `playTrackingApi.getStats`, `api/pendingTracks.ts` and this one. The pattern is consistent enough
 * to be worth stating — a wrapper written alongside an endpoint, and no screen ever built on it.
 * ADR-0077 later made that pattern a rule and deleted the `pendingTracks` wrapper; this page is
 * why `organizerApi` was not deleted with it — it has a screen, even if the server has no apply.
 *
 * **No apply button, and not out of caution.** `organizer.py` exposes `/templates`, `/preview` and
 * `/track/{id}/preview`. There is no route that moves a file, so there is nothing to call. The
 * plan said"no apply until the preview is trusted", which turns out to be the server's position
 * already.
 *
 * Note the paths: the router's prefix is `/library/organize`, not `/organizer` — the plan had it
 * wrong, and `api/metadata.ts` had it right.
 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { FolderTree, Loader2, ArrowRight } from 'lucide-react';

import { organizerApi, type OrganizeResult } from '../../api/metadata';
import { queryKeys } from '../../api/queryKeys';
import { AdminPage, AdminSection } from './AdminPage';

const PREVIEW_LIMIT = 100;

export function OrganizePage() {
  const [template, setTemplate] = useState<string | null>(null);
  const [previewed, setPreviewed] = useState(false);

  const { data: templates, isLoading: templatesLoading } = useQuery({
    queryKey: queryKeys.organizeTemplates.all,
    queryFn: () => organizerApi.getTemplates(),
  });

  // The first template is the default the server itself uses (`artist-album`), so the select is
  // never empty and never in a state the preview cannot run from.
  const selected = template ?? templates?.templates[0]?.template ?? null;

  const { data: preview, isFetching, error, refetch } = useQuery({
    queryKey: ['library', 'organize-preview', selected],
    queryFn: () => organizerApi.preview(selected!, PREVIEW_LIMIT),
    enabled: false,
    retry: false,
  });

  const runPreview = () => {
    setPreviewed(true);
    void refetch();
  };

  return (
    <AdminPage
      title="Organiser"
      subtitle="See where files would move under a naming template — nothing is renamed"
    >
      <AdminSection title="Template">
        <div className="bg-zinc-800/50 rounded-lg p-4 space-y-3">
          {templatesLoading ? (
            <p className="text-sm text-zinc-400">Loading templates…</p>
          ) : (
            <>
              <select
                value={selected ?? ''}
                onChange={(e) => setTemplate(e.target.value)}
                className="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-white"
              >
                {templates?.templates.map((t) => (
                  <option key={t.name} value={t.template}>
                    {t.name} — {t.template}
                  </option>
                ))}
              </select>
              {templates?.templates.find((t) => t.template === selected)?.example && (
                <p className="text-xs text-zinc-500 font-mono truncate">
                  e.g. {templates.templates.find((t) => t.template === selected)!.example}
                </p>
              )}
              <button
                onClick={runPreview}
                disabled={isFetching || !selected}
                className="px-4 py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-white text-sm font-medium flex items-center gap-2"
              >
                {isFetching ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <FolderTree className="w-4 h-4" />
                )}
                {isFetching ? 'Previewing…' : 'Preview'}
              </button>
              <p className="text-xs text-zinc-500">
                Previews the first {PREVIEW_LIMIT} tracks. Nothing is moved — the server has no
                route that renames a file.
              </p>
            </>
          )}
        </div>
      </AdminSection>

      {error && (
        <p className="text-sm text-red-400">
          The preview failed: {error instanceof Error ? error.message : 'unknown error'}
        </p>
      )}

      {previewed && !isFetching && preview && (
        <AdminSection
          title={`${preview.total.toLocaleString()} previewed · ${preview.moved.toLocaleString()} would move · ${preview.skipped.toLocaleString()} already correct${
            preview.errors > 0 ? ` · ${preview.errors.toLocaleString()} errors` : ''
          }`}
        >
          {preview.results.length === 0 ? (
            <p className="text-sm text-zinc-400">Nothing to show.</p>
          ) : (
            preview.results.map((result) => <ResultRow key={result.track_id} result={result} />)
          )}
        </AdminSection>
      )}
    </AdminPage>
  );
}

function ResultRow({ result }: { result: OrganizeResult }) {
  const tone =
    result.status === 'moved'
      ? 'bg-cyan-900/60 text-cyan-300'
      : result.status === 'error'
        ? 'bg-red-900/60 text-red-300'
        : 'bg-zinc-700 text-zinc-400';

  return (
    <div className="bg-zinc-800/50 rounded-lg p-3 flex items-start gap-3">
      <span className={`text-xs px-2 py-0.5 rounded flex-shrink-0 ${tone}`}>
        {/* "moved" is the service's word for a *would-move* in preview mode. Saying "moved" on a
            page that moves nothing is the kind of wording that makes people distrust a tool. */}
        {result.status === 'moved' ? 'Would move' : result.status === 'error' ? 'Error' : 'Unchanged'}
      </span>
      <div className="min-w-0 flex-1 text-xs">
        <div className="text-zinc-400 truncate font-mono">
          {result.old_path}
        </div>
        {result.new_path && result.status === 'moved' && (
          <div className="flex items-start gap-1 text-cyan-300 truncate font-mono mt-0.5">
            <ArrowRight className="w-3 h-3 flex-shrink-0 mt-0.5" />
            <span className="truncate">{result.new_path}</span>
          </div>
        )}
        {result.message && result.status !== 'moved' && (
          <div className="text-zinc-500 mt-0.5 truncate">{result.message}</div>
        )}
      </div>
    </div>
  );
}
