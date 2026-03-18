/**
 * DiscoverBrowser - Music discovery dashboard.
 *
 * Shows three sections:
 * - Unheard tracks by your top artists
 * - Deep cuts (least-played tracks by favorites)
 * - External artists to explore
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  Music,
  Loader2,
} from 'lucide-react';
import { libraryApi } from '../../../../api';
import { queryKeys } from '../../../../api/queryKeys';
import { STALE_TIME } from '../../../../api/queryDefaults';
import type { BrowserProps } from '../../types';
import { useOfflineStatus } from '../../../../hooks/useOfflineStatus';
import {
  useLibraryDiscovery,
  DiscoverySectionView,
  DiscoveryEmpty,
  CuratedPrompts,
  type DiscoveryItem,
} from '../../../Discovery';


export default function DiscoverBrowser({ onGoToArtist, onPlayTrack }: BrowserProps) {
  const discoverNavigate = useNavigate();
  const queryClient = useQueryClient();
  const { isOffline } = useOfflineStatus();

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: queryKeys.libraryDiscover.all,
    queryFn: () =>
      libraryApi.getDiscover({
        recommendations_limit: 12,
      }),
    enabled: !isOffline,
    staleTime: STALE_TIME.LONG,
  });

  const promptsQuery = useQuery({
    queryKey: queryKeys.curatedPrompts.all,
    queryFn: () => libraryApi.getCuratedPrompts(),
    enabled: !isOffline,
    staleTime: STALE_TIME.STATIC, // 30 min client-side; server caches 4h
  });

  const { sections, hasDiscovery } = useLibraryDiscovery({ data });

  if (isOffline) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-zinc-500 gap-2 p-6 text-center">
        <p className="text-zinc-300">Discovery is not available offline.</p>
        <p className="text-sm">Reconnect to load recommendations and new releases.</p>
      </div>
    );
  }

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
        <p>Unable to load discovery data. Check your connection and try again.</p>
        <button
          onClick={() => refetch()}
          className="px-3 py-1.5 text-sm bg-zinc-700 hover:bg-zinc-600 rounded-md text-zinc-300"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-zinc-400" />
      </div>
    );
  }

  const { recently_added_count } = data;

  const handleGoToArtist = (artistName: string) => {
    if (onGoToArtist) {
      onGoToArtist(artistName);
    } else {
      discoverNavigate(`/library/artists/${encodeURIComponent(artistName)}`);
    }
  };

  const handleItemClick = (item: DiscoveryItem) => {
    if (item.inLibrary && item.entityType === 'artist') {
      handleGoToArtist(item.name);
    }
  };

  const handleItemPlay = (item: DiscoveryItem) => {
    if (item.playbackContext?.trackId) {
      onPlayTrack(item.playbackContext.trackId);
    }
  };

  // Empty state
  if (!hasDiscovery) {
    return (
      <div className="h-full overflow-y-auto p-4">
        <DiscoveryEmpty
          message="No discoveries yet. Play some music to get personalized recommendations."
        />
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-4 space-y-8">
      {/* AI-generated listening suggestions */}
      <CuratedPrompts
        prompts={promptsQuery.data?.prompts ?? []}
        loading={promptsQuery.isLoading || promptsQuery.isFetching}
        onRefresh={() => {
          queryClient.fetchQuery({
            queryKey: queryKeys.curatedPrompts.all,
            queryFn: () => libraryApi.getCuratedPrompts({ refresh: true }),
            staleTime: 0,
          });
        }}
      />

      {/* Stats banner */}
      {recently_added_count > 0 && (
        <div className="flex gap-4 text-sm text-zinc-400">
          <span className="flex items-center gap-1">
            <Music className="w-4 h-4" />
            {recently_added_count} tracks added recently
          </span>
        </div>
      )}

      {/* Discovery sections */}
      {sections.map((section) => (
        <section key={section.id}>
          <DiscoverySectionView
            section={section}
            showHeader={true}
            gridColumns={6}
            onItemClick={handleItemClick}
            onItemPlay={handleItemPlay}
          />
        </section>
      ))}
    </div>
  );
}
