/**
 * SpotifyBrowser - Browse your Spotify library with local match status.
 *
 * Upload a ZIP from Spotify's "Download your data" page to see
 * your favorites, playlists, and listening stats with match indicators.
 */
import { useState, useCallback, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Disc3,
  Upload,
  Loader2,
  RefreshCw,
  Trash2,
  Heart,
  ListMusic,
  BarChart3,
  Check,
  X,
  FileDown,
} from 'lucide-react';
import { spotifyApi } from '../../../api/spotify';
import type { SpotifyImportData } from '../../../api/spotify';
import type { MatchingProgress } from '../../../api/spotify';
import { queryKeys } from '../../../api/queryKeys';
import { STALE_TIME } from '../../../api/queryDefaults';
import { registerBrowser, type BrowserProps } from '../types';
import {
  useSpotifyDiscovery,
  DiscoverySectionView,
  type DiscoveryItem,
} from '../../Discovery';

type Tab = 'favorites' | 'playlists' | 'stats';
type MatchFilter = 'all' | 'matched' | 'missing';

registerBrowser(
  {
    id: 'spotify',
    name: 'Spotify Library',
    description: "Browse your Spotify favorites and see what's in your collection",
    icon: 'Disc3',
    category: 'discovery',
    requiresFeatures: false,
    requiresEmbeddings: false,
  },
  SpotifyBrowser,
);

export function SpotifyBrowser({ onPlayTrack }: BrowserProps) {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<Tab>('favorites');
  const [matchFilter, setMatchFilter] = useState<MatchFilter>('all');

  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.spotifyImport.all,
    queryFn: () => spotifyApi.get(),
    staleTime: STALE_TIME.MEDIUM,
  });

  const isPending = data?.summary?.matching_status === 'pending';
  const [matchProgress, setMatchProgress] = useState<MatchingProgress | null>(null);

  // Auto-refresh every 5s while matching is pending
  useEffect(() => {
    if (!isPending) return;
    const interval = setInterval(() => {
      queryClient.invalidateQueries({ queryKey: queryKeys.spotifyImport.all });
    }, 5000);
    return () => clearInterval(interval);
  }, [isPending, queryClient]);

  // Poll Redis progress every 2s while pending
  useEffect(() => {
    if (!isPending) {
      setMatchProgress(null);
      return;
    }
    const poll = async () => {
      const p = await spotifyApi.getProgress();
      setMatchProgress(p);
    };
    poll();
    const id = setInterval(poll, 2000);
    return () => clearInterval(id);
  }, [isPending]);

  const uploadMutation = useMutation({
    mutationFn: (file: File) => spotifyApi.upload(file),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.spotifyImport.all }),
  });

  const rematchMutation = useMutation({
    mutationFn: () => spotifyApi.rematch(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.spotifyImport.all }),
  });

  const deleteMutation = useMutation({
    mutationFn: () => spotifyApi.remove(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.spotifyImport.all }),
  });

  const handleFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) uploadMutation.mutate(file);
    },
    [uploadMutation],
  );

  const { sections } = useSpotifyDiscovery({ data, tab, matchFilter });

  const handleItemPlay = (item: DiscoveryItem) => {
    if (item.playbackContext?.trackId) {
      onPlayTrack(item.playbackContext.trackId);
    }
  };

  if (isLoading) {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-zinc-400" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-zinc-500 gap-3">
        <p>Failed to load Spotify import data.</p>
      </div>
    );
  }

  // Empty state — no upload UI, user drops a ZIP anywhere in the app
  if (!data) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-center p-6 gap-4">
        <Disc3 className="w-12 h-12 text-zinc-600" />
        <div>
          <h3 className="text-lg font-medium text-zinc-300">No Spotify data imported</h3>
          <p className="text-sm text-zinc-500 mt-1">
            Drop a Spotify data export ZIP anywhere to get started
          </p>
        </div>
        <label className="inline-flex items-center gap-2 px-4 py-2 bg-zinc-700 hover:bg-zinc-600 text-zinc-200 rounded-lg cursor-pointer transition-colors text-sm">
          <FileDown className="w-4 h-4" />
          Or select a ZIP file
          <input type="file" accept=".zip" onChange={handleFileSelect} className="hidden" />
        </label>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col min-h-0">
      {/* Header */}
      <div className="flex-shrink-0 px-4 pt-3 pb-2 space-y-2">
        <SummaryBanner data={data} />
        {isPending && (
          <div className="flex items-center gap-2 text-xs text-zinc-400 bg-zinc-800/50 rounded-lg px-3 py-2">
            <Loader2 className="w-3.5 h-3.5 animate-spin flex-shrink-0" />
            {matchProgress && matchProgress.total > 0
              ? `Matching tracks... ${matchProgress.matched.toLocaleString()}/${matchProgress.total.toLocaleString()}`
              : 'Matching tracks against your library...'}
          </div>
        )}
        <div className="flex items-center justify-between">
          <TabBar tab={tab} onTabChange={setTab} />
          <div className="flex items-center gap-2">
            <MatchFilterBar filter={matchFilter} onFilterChange={setMatchFilter} />
            <button
              onClick={() => rematchMutation.mutate()}
              disabled={rematchMutation.isPending}
              className="p-1.5 text-zinc-400 hover:text-zinc-200 rounded-md hover:bg-zinc-700/50 disabled:opacity-50"
              title="Re-match against current library"
            >
              <RefreshCw className={`w-4 h-4 ${rematchMutation.isPending ? 'animate-spin' : ''}`} />
            </button>
            <label className="p-1.5 text-zinc-400 hover:text-zinc-200 rounded-md hover:bg-zinc-700/50 cursor-pointer" title="Re-import">
              <Upload className="w-4 h-4" />
              <input type="file" accept=".zip" onChange={handleFileSelect} className="hidden" />
            </label>
            <button
              onClick={() => {
                if (confirm('Remove Spotify import data?')) deleteMutation.mutate();
              }}
              className="p-1.5 text-zinc-400 hover:text-red-400 rounded-md hover:bg-zinc-700/50"
              title="Remove import"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-6">
        {sections.length === 0 ? (
          <div className="text-center text-zinc-500 py-12">
            No {matchFilter === 'matched' ? 'matched' : matchFilter === 'missing' ? 'missing' : ''} tracks in this view.
          </div>
        ) : (
          sections.map((section) => (
            <section key={section.id}>
              <DiscoverySectionView
                section={section}
                showHeader={true}
                gridColumns={6}
                onItemPlay={handleItemPlay}
              />
            </section>
          ))
        )}
      </div>
    </div>
  );
}

// ---- Sub-components ----

function SummaryBanner({ data }: { data: SpotifyImportData }) {
  const s = data.summary;
  const pct = s.total_favorites > 0
    ? Math.round((s.matched_favorites / s.total_favorites) * 100)
    : 0;

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
      {data.spotify_username && (
        <span className="text-zinc-400">{data.spotify_username}</span>
      )}
      <span className="text-zinc-300">
        {s.total_favorites.toLocaleString()} favorites
      </span>
      <span className="text-zinc-500">·</span>
      <span className={pct >= 70 ? 'text-green-400' : pct >= 40 ? 'text-yellow-400' : 'text-red-400'}>
        {s.matched_favorites.toLocaleString()} in library ({pct}%)
      </span>
      <span className="text-zinc-500">·</span>
      <span className="text-zinc-400">
        {s.total_playlists} playlists
      </span>
      {data.streaming_stats.total_ms > 0 && (
        <>
          <span className="text-zinc-500">·</span>
          <span className="text-zinc-400">
            {Math.round(data.streaming_stats.total_ms / 3600000).toLocaleString()}h streamed
          </span>
        </>
      )}
    </div>
  );
}

function TabBar({ tab, onTabChange }: { tab: Tab; onTabChange: (t: Tab) => void }) {
  const tabs: { id: Tab; label: string; icon: React.ReactNode }[] = [
    { id: 'favorites', label: 'Favorites', icon: <Heart className="w-3.5 h-3.5" /> },
    { id: 'playlists', label: 'Playlists', icon: <ListMusic className="w-3.5 h-3.5" /> },
    { id: 'stats', label: 'Stats', icon: <BarChart3 className="w-3.5 h-3.5" /> },
  ];

  return (
    <div className="flex gap-1">
      {tabs.map((t) => (
        <button
          key={t.id}
          onClick={() => onTabChange(t.id)}
          className={`flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-md transition-colors ${
            tab === t.id
              ? 'bg-zinc-700 text-zinc-100'
              : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800'
          }`}
        >
          {t.icon}
          {t.label}
        </button>
      ))}
    </div>
  );
}

function MatchFilterBar({
  filter,
  onFilterChange,
}: {
  filter: MatchFilter;
  onFilterChange: (f: MatchFilter) => void;
}) {
  const filters: { id: MatchFilter; label: string; icon?: React.ReactNode }[] = [
    { id: 'all', label: 'All' },
    { id: 'matched', label: 'In Library', icon: <Check className="w-3 h-3 text-green-400" /> },
    { id: 'missing', label: 'Missing', icon: <X className="w-3 h-3 text-red-400" /> },
  ];

  return (
    <div className="flex gap-0.5 bg-zinc-800/50 rounded-md p-0.5">
      {filters.map((f) => (
        <button
          key={f.id}
          onClick={() => onFilterChange(f.id)}
          className={`flex items-center gap-1 px-2 py-1 text-xs rounded transition-colors ${
            filter === f.id
              ? 'bg-zinc-700 text-zinc-200'
              : 'text-zinc-500 hover:text-zinc-300'
          }`}
        >
          {f.icon}
          {f.label}
        </button>
      ))}
    </div>
  );
}
