import { useMemo } from 'react';
import type { DiscoverySection, DiscoveryItem } from '../types';
import type { LibraryDiscoverResponse } from '../../../api';

interface UseLibraryDiscoveryOptions {
  data: LibraryDiscoverResponse | null | undefined;
}

interface UseLibraryDiscoveryResult {
  sections: DiscoverySection[];
  hasDiscovery: boolean;
}

/**
 * Transform library discover data into discovery sections
 *
 * Returns three sections:
 * - "Unheard in Your Library" - tracks by top artists never played
 * - "Deep Cuts by Your Favorites" - least-played tracks by top artists
 * - "Artists to Explore" - external recommended artists
 */
export function useLibraryDiscovery({
  data,
}: UseLibraryDiscoveryOptions): UseLibraryDiscoveryResult {
  return useMemo(() => {
    if (!data) {
      return { sections: [], hasDiscovery: false };
    }

    const sections: DiscoverySection[] = [];

    // Section 1: Unheard tracks by top artists
    if (data.unheard_tracks && data.unheard_tracks.length > 0) {
      const items: DiscoveryItem[] = data.unheard_tracks.map((track) => ({
        id: track.id,
        entityType: 'track' as const,
        name: track.title || 'Unknown Track',
        subtitle: track.artist || 'Unknown Artist',
        inLibrary: true,
        playbackContext: {
          artist: track.artist || '',
          album: track.album || undefined,
          trackId: track.id,
        },
      }));

      sections.push({
        id: 'unheard-tracks',
        title: 'Unheard in Your Library',
        description: "Tracks by artists you love that you haven't played yet",
        entityType: 'track',
        items,
        layout: 'tracklist',
        rawTracks: data.unheard_tracks,
      });
    }

    // Section 2: Deep cuts (low play count)
    if (data.deep_cuts && data.deep_cuts.length > 0) {
      const items: DiscoveryItem[] = data.deep_cuts.map((track) => ({
        id: track.id,
        entityType: 'track' as const,
        name: track.title || 'Unknown Track',
        subtitle: `${track.artist || 'Unknown Artist'} · ${track.play_count} ${track.play_count === 1 ? 'play' : 'plays'}`,
        inLibrary: true,
        playbackContext: {
          artist: track.artist || '',
          album: track.album || undefined,
          trackId: track.id,
        },
      }));

      sections.push({
        id: 'deep-cuts',
        title: 'Deep Cuts by Your Favorites',
        description: 'Least-played tracks by your most-played artists',
        entityType: 'track',
        items,
        layout: 'tracklist',
        rawTracks: data.deep_cuts,
      });
    }

    // Section 3: External recommended artists
    if (data.recommended_artists && data.recommended_artists.length > 0) {
      const items: DiscoveryItem[] = data.recommended_artists.map((artist) => ({
        entityType: 'artist' as const,
        name: artist.name,
        subtitle: `Similar to ${artist.based_on_artist}`,
        imageUrl: artist.image_url || undefined,
        matchScore: artist.match_score,
        inLibrary: false,
        externalLinks: {
          bandcamp: artist.bandcamp_url || undefined,
          lastfm: artist.lastfm_url || undefined,
        },
      }));

      sections.push({
        id: 'external-artists',
        title: 'Artists to Explore',
        description: "Artists similar to your favorites that aren't in your library yet",
        entityType: 'artist',
        items,
        layout: 'grid',
      });
    }

    return {
      sections,
      hasDiscovery: sections.some((s) => s.items.length > 0),
    };
  }, [data]);
}
