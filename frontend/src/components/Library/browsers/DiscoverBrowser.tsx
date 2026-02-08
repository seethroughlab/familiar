/**
 * DiscoverBrowser - Music discovery dashboard.
 *
 * Aggregates discovery features using unified Discovery components:
 * - New releases from library artists
 * - Recommended artists based on listening patterns
 * - Unmatched Spotify favorites
 */
import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import {
  Disc,
  Music,
  Sparkles,
  Loader2,
  ChevronRight,
} from 'lucide-react';
import { libraryApi, playlistsApi } from '../../../api/client';
import { registerBrowser, type BrowserProps } from '../types';
import {
  useLibraryDiscovery,
  DiscoverySectionView,
  DiscoveryEmpty,
  type DiscoveryItem,
} from '../../Discovery';

import { createLogger } from '../../../utils/logger';

const log = createLogger('DiscoverBrowser');

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
  const [, setSearchParams] = useSearchParams();

  const { data, isLoading, error } = useQuery({
    queryKey: ['library-discover'],
    queryFn: () =>
      libraryApi.getDiscover({
        releases_limit: 8,
        recommendations_limit: 12,
        favorites_limit: 6,
      }),
    staleTime: 5 * 60 * 1000, // Cache for 5 minutes
  });

  const {
    newReleasesSection,
    inLibraryArtistsSection,
    externalArtistsSection,
    unmatchedFavoritesSection,
    hasDiscovery,
  } = useLibraryDiscovery({ data });

  if (isLoading) {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-zinc-400" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="h-full flex items-center justify-center text-zinc-500">
        <p>Unable to load discovery data</p>
      </div>
    );
  }

  const {
    new_releases_total,
    unmatched_total,
    recently_added_count,
  } = data;

  const handleGoToArtist = (artistName: string) => {
    if (onGoToArtist) {
      onGoToArtist(artistName);
    } else {
      setSearchParams({ artistDetail: artistName });
    }
  };

  const handleItemClick = (item: DiscoveryItem) => {
    if (item.inLibrary && item.entityType === 'artist') {
      handleGoToArtist(item.name);
    }
  };

  const handleAddToWishlist = async (item: DiscoveryItem) => {
    if (!item.inLibrary && item.name) {
      try {
        if (item.entityType === 'artist') {
          // For artists, add a placeholder track
          await playlistsApi.addToWishlist({
            title: `Tracks by ${item.name}`,
            artist: item.name,
          });
        } else {
          await playlistsApi.addToWishlist({
            title: item.name,
            artist: item.subtitle || 'Unknown Artist',
            album: item.playbackContext?.album,
          });
        }
      } catch (err) {
        log.error('Failed to add to wishlist:', err);
      }
    }
  };

  // Empty state
  if (!hasDiscovery) {
    return (
      <div className="h-full overflow-y-auto p-4">
        <DiscoveryEmpty
          message="No discoveries yet. Play some music to get personalized recommendations, or connect Spotify to import your favorites."
        />
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-4 space-y-8">
      {/* Stats banner */}
      <div className="flex gap-4 text-sm text-zinc-400">
        {recently_added_count > 0 && (
          <span className="flex items-center gap-1">
            <Music className="w-4 h-4" />
            {recently_added_count} tracks added recently
          </span>
        )}
        {new_releases_total > 0 && (
          <span className="flex items-center gap-1">
            <Disc className="w-4 h-4" />
            {new_releases_total} new releases
          </span>
        )}
        {unmatched_total > 0 && (
          <span className="flex items-center gap-1">
            <Sparkles className="w-4 h-4" />
            {unmatched_total} tracks to get
          </span>
        )}
      </div>

      {/* New Releases */}
      {newReleasesSection && newReleasesSection.items.length > 0 && (
        <section>
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold flex items-center gap-2">
              <Disc className="w-5 h-5 text-purple-500" />
              New Releases from Your Artists
            </h3>
            {new_releases_total > newReleasesSection.items.length && (
              <button className="text-sm text-zinc-400 hover:text-white flex items-center gap-1">
                View all {new_releases_total}
                <ChevronRight className="w-4 h-4" />
              </button>
            )}
          </div>
          <DiscoverySectionView
            section={newReleasesSection}
            showHeader={false}
            gridColumns={4}
            onItemClick={handleItemClick}
            onAddToWishlist={handleAddToWishlist}
          />
        </section>
      )}

      {/* Recommended Artists in Library */}
      {inLibraryArtistsSection && inLibraryArtistsSection.items.length > 0 && (
        <section>
          <DiscoverySectionView
            section={inLibraryArtistsSection}
            showHeader={true}
            gridColumns={6}
            onItemClick={handleItemClick}
            onAddToWishlist={handleAddToWishlist}
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
            onAddToWishlist={handleAddToWishlist}
          />
        </section>
      )}

      {/* Unmatched Spotify Favorites */}
      {unmatchedFavoritesSection && unmatchedFavoritesSection.items.length > 0 && (
        <section>
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold flex items-center gap-2">
              <Sparkles className="w-5 h-5 text-green-500" />
              Get These From Spotify
            </h3>
            {unmatched_total > unmatchedFavoritesSection.items.length && (
              <span className="text-sm text-zinc-500">
                {unmatched_total} total
              </span>
            )}
          </div>
          <DiscoverySectionView
            section={unmatchedFavoritesSection}
            showHeader={false}
            onAddToWishlist={handleAddToWishlist}
          />
        </section>
      )}
    </div>
  );
}
