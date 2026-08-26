/**
 * Duplicates (ADR-0058 phase 4) — a front end for `POST /library/deduplicate/preview`.
 *
 * **The scan runs only when asked.** It is a POST that reads every active track and groups them by
 * normalised (artist, album, title); running it on mount would mean a whole-library sweep every
 * time someone opened the page. `enabled: false` plus an explicit `refetch()` is what enforces
 * that, and the plan called for it before the code existed.
 *
 * **Preview only, and that is the server's shape, not a caution here.** `library_deduplicate.py`
 * exposes exactly one route. There is no apply, no delete, nothing this page could call to remove a
 * file even if it offered the button — so it does not offer one, and says so rather than implying
 * a missing feature.
 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Copy, Search, Loader2 } from 'lucide-react';

import { libraryApi, type DuplicateGroup, type DuplicateTrackInfo } from '../../api/library';
import { AdminPage, AdminSection } from './AdminPage';

export function DuplicatesPage() {
  const [search, setSearch] = useState('');
  const [scanned, setScanned] = useState(false);

  const { data, isFetching, error, refetch } = useQuery({
    queryKey: ['library', 'duplicates', search],
    queryFn: () => libraryApi.deduplicatePreview(search ? { search } : undefined),
    enabled: false,
    retry: false,
  });

  const runScan = () => {
    setScanned(true);
    void refetch();
  };

  return (
    <AdminPage
      title="Duplicates"
      subtitle="Find tracks that appear more than once, and which copy is the better one"
    >
      <AdminSection title="Scan">
        <div className="bg-zinc-800/50 rounded-lg p-4 space-y-3">
          <p className="text-sm text-zinc-400">
            Groups tracks by artist, album and title after normalising them. The copy ranked highest
            on format and metadata completeness is the one it would keep.
          </p>
          <div className="flex gap-2">
            <div className="relative flex-1">
              <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && runScan()}
                placeholder="Narrow to a title, artist or album (optional)"
                className="w-full bg-zinc-900 border border-zinc-700 rounded-lg pl-9 pr-3 py-2 text-sm text-white"
              />
            </div>
            <button
              onClick={runScan}
              disabled={isFetching}
              className="px-4 py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-white text-sm font-medium flex items-center gap-2 flex-shrink-0"
            >
              {isFetching ? <Loader2 className="w-4 h-4 animate-spin" /> : <Copy className="w-4 h-4" />}
              {isFetching ? 'Scanning…' : 'Scan'}
            </button>
          </div>
          <p className="text-xs text-zinc-500">
            Scans the whole library unless you narrow it. Nothing is deleted — this is a preview,
            and the server has no route that removes a file.
          </p>
        </div>
      </AdminSection>

      {error && (
        <p className="text-sm text-red-400">
          The scan failed: {error instanceof Error ? error.message : 'unknown error'}
        </p>
      )}

      {scanned && !isFetching && data && (
        <AdminSection
          title={
            data.total_groups === 0
              ? 'No duplicates found'
              : `${data.total_groups.toLocaleString()} groups · ${data.total_duplicates.toLocaleString()} duplicate files`
          }
        >
          {data.groups.map((group) => (
            <DuplicateGroupCard key={group.normalized_key} group={group} />
          ))}
          {/*
            * The endpoint returns every group it finds, so a count that disagrees with the list
            * would mean the response itself was truncated — worth surfacing rather than hiding.
            */}
          {data.groups.length < data.total_groups && (
            <p className="text-xs text-zinc-500">
              Showing {data.groups.length.toLocaleString()} of {data.total_groups.toLocaleString()}.
            </p>
          )}
        </AdminSection>
      )}
    </AdminPage>
  );
}

function DuplicateGroupCard({ group }: { group: DuplicateGroup }) {
  return (
    <div className="bg-zinc-800/50 rounded-lg p-4 space-y-2">
      <div className="text-sm font-medium text-white truncate">
        {group.keep.title ?? 'Untitled'}
        {group.keep.artist && <span className="text-zinc-500"> — {group.keep.artist}</span>}
      </div>
      <TrackRow track={group.keep} verdict="keep" />
      {group.remove.map((track) => (
        <TrackRow key={track.id} track={track} verdict="duplicate" />
      ))}
    </div>
  );
}

function TrackRow({ track, verdict }: { track: DuplicateTrackInfo; verdict: 'keep' | 'duplicate' }) {
  const keep = verdict === 'keep';
  return (
    <div className="flex items-start gap-3 bg-zinc-900/50 rounded p-2">
      <span
        className={`text-xs px-2 py-0.5 rounded flex-shrink-0 ${
          keep ? 'bg-emerald-900/60 text-emerald-300' : 'bg-zinc-700 text-zinc-400'
        }`}
      >
        {keep ? 'Keep' : 'Duplicate'}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-xs text-zinc-400 truncate">
          {track.file_path}
        </div>
        <div className="text-xs text-zinc-500 mt-0.5">
          {track.quality}
          {track.format && ` · ${track.format}`} · {track.metadata_completeness}/6 metadata fields
        </div>
      </div>
    </div>
  );
}
