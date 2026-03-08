/**
 * DiscoverBrowser - Music discovery dashboard.
 *
 * Aggregates discovery features using unified Discovery components:
 * - New releases from library artists
 * - Recommended artists based on listening patterns
 */
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  Music,
  Loader2,
} from 'lucide-react';
import { libraryApi } from '../../../api';
import { registerBrowser, type BrowserProps } from '../types';
import { useOfflineStatus } from '../../../hooks/useOfflineStatus';
import {
  useLibraryDiscovery,
  DiscoverySectionView,
  DiscoveryEmpty,
  type DiscoveryItem,
} from '../../Discovery';


// Register this browser
registerBrowser(
  {
    id: 'discover',
    name: 'Discover',
    description: 'New releases, recommendations, and music to explore',
    icon: 'Sparkles',
    category: 'discovery',
    requiresFeatures: false,
    requiresEmbeddings: false,
  },
  DiscoverBrowser
);

export function DiscoverBrowser({ onGoToArtist }: BrowserProps) {
  const discoverNavigate = useNavigate();
  const { isOffline } = useOfflineStatus();

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['library-discover'],
    queryFn: () =>
      libraryApi.getDiscover({
        recommendations_limit: 12,
        favorites_limit: 6,
      }),
    enabled: !isOffline,
    staleTime: 5 * 60 * 1000, // Cache for 5 minutes
  });

  const {
    inLibraryArtistsSection,
    externalArtistsSection,
    hasDiscovery,
  } = useLibraryDiscovery({ data });

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
      {/* Stats banner */}
      {recently_added_count > 0 && (
        <div className="flex gap-4 text-sm text-zinc-400">
          <span className="flex items-center gap-1">
            <Music className="w-4 h-4" />
            {recently_added_count} tracks added recently
          </span>
        </div>
      )}

      {/* Recommended Artists in Library */}
      {inLibraryArtistsSection && inLibraryArtistsSection.items.length > 0 && (
        <section>
          <DiscoverySectionView
            section={inLibraryArtistsSection}
            showHeader={true}
            gridColumns={6}
            onItemClick={handleItemClick}
          />
        </section>
      )}

      {/* Artists to Discover */}
      {externalArtistsSection && externalArtistsSection.items.length > 0 && (
        <section>
          <DiscoverySectionView
            section={externalArtistsSection}
            showHeader={true}
            gridColumns={6}
          />
        </section>
      )}

    </div>
  );
}
