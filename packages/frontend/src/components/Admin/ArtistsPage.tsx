/**
 * Artist cleanup — merging artists the scanner split, at `/tools/artists`.
 *
 * **Was a "browser" at `/library/artist-cleanup` until ADR-0081 point 4.** It is a job you run
 * against the library, which is what Tools means under ADR-0058 point 2, so it belongs beside
 * Duplicates, Artwork and Organiser rather than in a registry of things to browse. Moving it here
 * is what leaves the browser registry with a single member its only consumer bypasses — see
 * point 3.
 */
/**
 * Admin tool: merge canonical artist rows.
 *
 * Two paths:
 *   - **Suggestions** (auto): the `merge-suggestions` endpoint groups
 *     artists by `_canonicalize_for_match` so obvious clusters surface
 *     ("Beatles" / "The Beatles" / "Beatles, The"). User picks keep +
 *     merge candidates, hits Merge.
 *   - **Manual search** (Pass 4): for long-tail renames or
 *     abbreviations whose canonical forms don't collide ("Various" /
 *     "Various Artists", "Señor Coconut" / "Señor Coconut and His
 *     Orchestra"). User types a query, sees matching artists, picks
 *     2+ to merge.
 *
 * Different non-NULL MBIDs across selected candidates disable the
 * Merge button in either path — strong "do not merge" signal.
 */
import { useEffect, useMemo, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Users,
  Loader2,
  CheckCircle,
  AlertTriangle,
  Tag,
  TagIcon,
  Search,
} from 'lucide-react';
import { adminArtistsApi } from '../../api/admin';
import type {
  MergeSuggestion,
  MergeCandidate,
  ArtistSearchResult,
} from '../../api/admin';

export function ArtistsPage() {
  const queryClient = useQueryClient();
  const [recentlyMerged, setRecentlyMerged] = useState<{
    kept: string;
    repointed: number;
  } | null>(null);

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['admin', 'artists', 'merge-suggestions'],
    queryFn: () => adminArtistsApi.getMergeSuggestions(100),
    staleTime: 60_000,
  });

  const mergeMutation = useMutation({
    mutationFn: adminArtistsApi.mergeArtists,
    onSuccess: (resp, vars) => {
      setRecentlyMerged({
        kept: vars.keep_id,
        repointed: resp.tracks_repointed,
      });
      // Refetch suggestions and invalidate downstream caches that show
      // artist counts (the artist tile grid + detail).
      queryClient.invalidateQueries({
        queryKey: ['admin', 'artists', 'merge-suggestions'],
      });
      queryClient.invalidateQueries({ queryKey: ['library', 'artists'] });
    },
  });

  if (isLoading) {
    return (
      <div className="bg-zinc-800/50 rounded-lg p-4">
        <div className="flex items-center gap-3">
          <Loader2 className="w-5 h-5 animate-spin text-zinc-400" />
          <span className="text-zinc-400">Loading merge suggestions…</span>
        </div>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="bg-zinc-800/50 rounded-lg p-4">
        <div className="flex items-center gap-3 text-red-400">
          <AlertTriangle className="w-5 h-5" />
          <span>Failed to load merge suggestions.</span>
          <button
            type="button"
            onClick={() => refetch()}
            className="ml-auto text-xs text-zinc-300 hover:text-white underline"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  const suggestions = data?.suggestions ?? [];

  return (
    <div className="bg-zinc-800/50 rounded-lg p-4 space-y-3">
      <div className="flex items-center gap-3">
        <Users className="w-5 h-5 text-zinc-300" />
        <div>
          <div className="font-medium text-white">Merge duplicate artists</div>
          <div className="text-sm text-zinc-400">
            Combine artist tiles that point to the same real artist
            (e.g. <span className="font-mono text-zinc-300">Beatles</span> /
            <span className="font-mono text-zinc-300"> The Beatles</span>).
          </div>
        </div>
      </div>

      {recentlyMerged && (
        <div className="flex items-center gap-2 text-sm text-emerald-400 bg-emerald-500/10 rounded px-3 py-2">
          <CheckCircle className="w-4 h-4" />
          Merged. {recentlyMerged.repointed} tracks repointed.
        </div>
      )}

      {suggestions.length === 0 && (
        <div className="text-sm text-zinc-400 italic">
          No automatic merge suggestions right now. Anything left is
          either already canonical, or needs manual review (e.g. an
          artist that's been renamed by MusicBrainz — the strict-match
          resolver leaves those as separate rows).
        </div>
      )}

      {suggestions.length > 0 && (
        <div className="space-y-3">
          {suggestions.map((s) => (
            <MergeSuggestionRow
              key={s.canonical_form}
              suggestion={s}
              onMerge={(req) => mergeMutation.mutate(req)}
              isPending={mergeMutation.isPending}
            />
          ))}
        </div>
      )}

      <ManualMergeSearch
        onMerge={(req) => mergeMutation.mutate(req)}
        isPending={mergeMutation.isPending}
      />
    </div>
  );
}

interface MergeSuggestionRowProps {
  suggestion: MergeSuggestion;
  onMerge: (req: { keep_id: string; merge_ids: string[] }) => void;
  isPending: boolean;
}

function MergeSuggestionRow({
  suggestion,
  onMerge,
  isPending,
}: MergeSuggestionRowProps) {
  const [keepId, setKeepId] = useState<string>(suggestion.suggested_keep_id);
  const [mergeIds, setMergeIds] = useState<Set<string>>(
    () =>
      new Set(
        suggestion.candidates
          .map((c) => c.id)
          .filter((id) => id !== suggestion.suggested_keep_id),
      ),
  );

  const toggleMerge = (id: string) => {
    if (id === keepId) return; // can't merge the keep
    setMergeIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // MBID guard: don't allow merging two candidates that have different
  // non-NULL MBIDs (strong "do not merge" signal).
  const selectedCandidates = suggestion.candidates.filter(
    (c) => c.id === keepId || mergeIds.has(c.id),
  );
  const distinctMbids = new Set(
    selectedCandidates
      .map((c) => c.musicbrainz_id)
      .filter((id): id is string => Boolean(id)),
  );
  const mbidConflict = distinctMbids.size > 1;
  const canMerge = mergeIds.size > 0 && !mbidConflict && !isPending;

  return (
    <div className="border border-zinc-700 rounded-lg p-3 space-y-2">
      <div className="text-xs font-mono text-zinc-500">
        Canonical form: {suggestion.canonical_form}
      </div>
      <div className="space-y-1.5">
        {suggestion.candidates.map((c) => (
          <CandidateRow
            key={c.id}
            candidate={c}
            isKeep={c.id === keepId}
            isMerge={mergeIds.has(c.id)}
            onSelectKeep={() => {
              setKeepId(c.id);
              setMergeIds((prev) => {
                const next = new Set(prev);
                next.delete(c.id);
                return next;
              });
            }}
            onToggleMerge={() => toggleMerge(c.id)}
          />
        ))}
      </div>
      {mbidConflict && (
        <div className="flex items-center gap-2 text-xs text-amber-400">
          <AlertTriangle className="w-3.5 h-3.5" />
          Selected candidates have different MusicBrainz ids — likely
          different artists. Adjust the selection or merge fewer rows.
        </div>
      )}
      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          disabled={!canMerge}
          onClick={() =>
            onMerge({
              keep_id: keepId,
              merge_ids: Array.from(mergeIds),
            })
          }
          className="px-3 py-1.5 text-sm rounded bg-blue-600 hover:bg-blue-500 disabled:bg-zinc-700 disabled:text-zinc-500 disabled:cursor-not-allowed text-white"
        >
          {isPending ? (
            <span className="flex items-center gap-2">
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              Merging…
            </span>
          ) : (
            `Merge ${mergeIds.size} into keep`
          )}
        </button>
      </div>
    </div>
  );
}

interface CandidateRowProps {
  candidate: MergeCandidate;
  isKeep: boolean;
  isMerge: boolean;
  onSelectKeep: () => void;
  onToggleMerge: () => void;
}

function CandidateRow({
  candidate,
  isKeep,
  isMerge,
  onSelectKeep,
  onToggleMerge,
}: CandidateRowProps) {
  return (
    <div
      className={`flex items-center gap-3 rounded px-2 py-1.5 ${
        isKeep
          ? 'bg-blue-500/10 border border-blue-500/40'
          : isMerge
            ? 'bg-zinc-700/40'
            : 'hover:bg-zinc-700/20'
      }`}
    >
      <label className="flex items-center gap-1.5 text-xs text-zinc-300 cursor-pointer">
        <input
          type="radio"
          checked={isKeep}
          onChange={onSelectKeep}
          className="accent-blue-500"
        />
        Keep
      </label>
      <label
        className={`flex items-center gap-1.5 text-xs cursor-pointer ${
          isKeep ? 'text-zinc-600 cursor-not-allowed' : 'text-zinc-300'
        }`}
      >
        <input
          type="checkbox"
          checked={isMerge}
          disabled={isKeep}
          onChange={onToggleMerge}
          className="accent-blue-500"
        />
        Merge
      </label>
      <div className="flex-1 truncate text-sm text-white">{candidate.name}</div>
      <div className="text-xs text-zinc-400 tabular-nums">
        {candidate.track_count} tracks
      </div>
      {candidate.musicbrainz_id ? (
        <span className="flex items-center gap-1 text-xs text-emerald-400">
          <Tag className="w-3 h-3" />
          MBID
        </span>
      ) : (
        <span className="flex items-center gap-1 text-xs text-zinc-500">
          <TagIcon className="w-3 h-3" />
          no MBID
        </span>
      )}
    </div>
  );
}


// ── Manual search panel ──────────────────────────────────────────────


interface ManualMergeSearchProps {
  onMerge: (req: { keep_id: string; merge_ids: string[] }) => void;
  isPending: boolean;
}

function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(id);
  }, [value, delayMs]);
  return debounced;
}

function ManualMergeSearch({ onMerge, isPending }: ManualMergeSearchProps) {
  const [query, setQuery] = useState('');
  const debouncedQuery = useDebouncedValue(query, 250);
  const trimmed = debouncedQuery.trim();

  const [keepId, setKeepId] = useState<string | null>(null);
  const [mergeIds, setMergeIds] = useState<Set<string>>(new Set());

  const { data, isFetching } = useQuery({
    queryKey: ['admin', 'artists', 'search', trimmed],
    queryFn: () => adminArtistsApi.searchArtists(trimmed, 20),
    enabled: trimmed.length > 0,
    staleTime: 30_000,
  });

  const results = useMemo(() => data?.results ?? [], [data]);

  // Reset selection when results change.
  useEffect(() => {
    setKeepId(null);
    setMergeIds(new Set());
  }, [trimmed]);

  const toggleMerge = (id: string) => {
    if (id === keepId) return;
    setMergeIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selected: ArtistSearchResult[] = useMemo(
    () => results.filter((r) => r.id === keepId || mergeIds.has(r.id)),
    [results, keepId, mergeIds],
  );
  const distinctMbids = new Set(
    selected
      .map((r) => r.musicbrainz_id)
      .filter((id): id is string => Boolean(id)),
  );
  const mbidConflict = distinctMbids.size > 1;
  const canMerge =
    keepId !== null && mergeIds.size > 0 && !mbidConflict && !isPending;

  return (
    <div className="border-t border-zinc-700 pt-3 space-y-2">
      <div className="flex items-center gap-2 text-sm text-zinc-300">
        <Search className="w-4 h-4 text-zinc-500" />
        <span>Find more</span>
        <span className="text-xs text-zinc-500">
          (long-tail renames the auto-suggester misses)
        </span>
      </div>
      <input
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search artists by name…"
        className="w-full px-3 py-1.5 text-sm rounded bg-zinc-900/60 border border-zinc-700 text-white placeholder:text-zinc-500 focus:outline-none focus:border-blue-500"
      />
      {trimmed.length > 0 && isFetching && (
        <div className="flex items-center gap-2 text-xs text-zinc-500">
          <Loader2 className="w-3 h-3 animate-spin" />
          Searching…
        </div>
      )}
      {trimmed.length > 0 && !isFetching && results.length === 0 && (
        <div className="text-xs text-zinc-500 italic">
          No artists match "{trimmed}".
        </div>
      )}
      {results.length > 0 && (
        <div className="border border-zinc-700 rounded-lg p-3 space-y-2">
          <div className="space-y-1.5">
            {results.map((r) => {
              const candidate: MergeCandidate = {
                id: r.id,
                name: r.name,
                sort_name: r.sort_name,
                track_count: r.track_count,
                musicbrainz_id: r.musicbrainz_id,
              };
              return (
                <CandidateRow
                  key={r.id}
                  candidate={candidate}
                  isKeep={r.id === keepId}
                  isMerge={mergeIds.has(r.id)}
                  onSelectKeep={() => {
                    setKeepId(r.id);
                    setMergeIds((prev) => {
                      const next = new Set(prev);
                      next.delete(r.id);
                      return next;
                    });
                  }}
                  onToggleMerge={() => toggleMerge(r.id)}
                />
              );
            })}
          </div>
          {mbidConflict && (
            <div className="flex items-center gap-2 text-xs text-amber-400">
              <AlertTriangle className="w-3.5 h-3.5" />
              Selected candidates have different MusicBrainz ids — likely
              different artists. Adjust the selection or merge fewer rows.
            </div>
          )}
          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              disabled={!canMerge}
              onClick={() =>
                keepId &&
                onMerge({
                  keep_id: keepId,
                  merge_ids: Array.from(mergeIds),
                })
              }
              className="px-3 py-1.5 text-sm rounded bg-blue-600 hover:bg-blue-500 disabled:bg-zinc-700 disabled:text-zinc-500 disabled:cursor-not-allowed text-white"
            >
              {isPending ? (
                <span className="flex items-center gap-2">
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  Merging…
                </span>
              ) : keepId === null ? (
                'Pick a Keep first'
              ) : (
                `Merge ${mergeIds.size} into keep`
              )}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
