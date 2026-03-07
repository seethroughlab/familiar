import { useMemo } from 'react';
import type { DiscoverySection, DiscoveryItem } from '../types';
import type { LibraryDiscoverResponse } from '../../../api';
import { libraryApi } from '../../../api';

interface UseLibraryDiscoveryOptions {
  data: LibraryDiscoverResponse | null | undefined;
}

interface UseLibraryDiscoveryResult {
  sections: DiscoverySection[];
  inLibraryArtistsSection: DiscoverySection | null;
  externalArtistsSection: DiscoverySection | null;
  hasDiscovery: boolean;
}

/**
 * Transform library discover data into discovery sections
 *
 * Returns multiple sections:
 * - "New Releases" - new releases from artists in library
 * - "More From Artists You Love" - in-library recommended artists
 * - "Artists to Discover" - external recommended artists
 */
export function useLibraryDiscovery({
  data,
}: UseLibraryDiscoveryOptions): UseLibraryDiscoveryResult {
  return useMemo(() => {
    if (!data) {
      return {
        sections: [],
        inLibraryArtistsSection: null,
        externalArtistsSection: null,
        hasDiscovery: false,
      };
    }

    const sections: DiscoverySection[] = [];

    // Section 1 & 2: Recommended Artists (split by in-library status)
    let inLibraryArtistsSection: DiscoverySection | null = null;
    let externalArtistsSection: DiscoverySection | null = null;

    if (data.recommended_artists && data.recommended_artists.length > 0) {
      const inLibraryArtists = data.recommended_artists.filter((a) => a.in_library);
      const externalArtists = data.recommended_artists.filter((a) => !a.in_library);

      if (inLibraryArtists.length > 0) {
        const inLibraryItems: DiscoveryItem[] = inLibraryArtists.map((artist) => ({
          entityType: 'artist' as const,
          name: artist.name,
          subtitle: `${artist.track_count} tracks`,
          imageUrl: libraryApi.getArtistImageUrl(artist.name, 'large'),
          matchScore: artist.match_score,
          matchReason: `Similar to ${artist.based_on_artist}`,
          inLibrary: true,
          playbackContext: { artist: artist.name },
        }));

        inLibraryArtistsSection = {
          id: 'in-library-artists',
          title: 'More From Artists You Love',
          entityType: 'artist',
          items: inLibraryItems,
          layout: 'grid',
        };
        sections.push(inLibraryArtistsSection);
      }

      if (externalArtists.length > 0) {
        const externalItems: DiscoveryItem[] = externalArtists.map((artist) => ({
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

        externalArtistsSection = {
          id: 'external-artists',
          title: 'Artists to Discover',
          entityType: 'artist',
          items: externalItems,
          layout: 'grid',
        };
        sections.push(externalArtistsSection);
      }
    }

    return {
      sections,
      inLibraryArtistsSection,
      externalArtistsSection,
      hasDiscovery: sections.some((s) => s.items.length > 0),
    };
  }, [data]);
}
