import { useMemo } from 'react';
import type { DiscoverySection, DiscoveryItem } from '../types';
import { libraryApi } from '../../../api';

// Similar artist structure
interface SimilarArtist {
  name: string;
  match_score: number;
  in_library: boolean;
  track_count: number | null;
  image_url: string | null;
  lastfm_url: string | null;
  bandcamp_url: string | null;
}

// Partial type for the fields we need from ArtistDetailResponse
interface ArtistDiscoveryData {
  similar_artists?: SimilarArtist[];
}

interface UseArtistDiscoveryOptions {
  artist: ArtistDiscoveryData | null | undefined;
  limit?: number;
}

interface UseArtistDiscoveryResult {
  sections: DiscoverySection[];
  hasDiscovery: boolean;
}

/**
 * Transform artist detail data into discovery sections
 *
 * Returns one section:
 * - "Similar Artists" - artists similar to the current one
 */
export function useArtistDiscovery({
  artist,
  limit = 20,
}: UseArtistDiscoveryOptions): UseArtistDiscoveryResult {
  const sections = useMemo(() => {
    if (!artist || !artist.similar_artists || artist.similar_artists.length === 0) {
      return [];
    }

    const similarArtistItems: DiscoveryItem[] = artist.similar_artists
      .slice(0, limit)
      .map((similar) => ({
        entityType: 'artist' as const,
        name: similar.name,
        subtitle: similar.in_library
          ? `${similar.track_count} tracks`
          : undefined,
        imageUrl: similar.in_library
          ? libraryApi.getArtistImageUrl(similar.name, 'large')
          : similar.image_url || undefined,
        matchScore: similar.match_score,
        inLibrary: similar.in_library,
        externalLinks: similar.in_library
          ? undefined
          : {
              bandcamp: similar.bandcamp_url || undefined,
              lastfm: similar.lastfm_url || undefined,
              amazon: `https://www.amazon.com/s?k=${encodeURIComponent(similar.name)}&i=digital-music`,
              apple: `https://music.apple.com/us/search?term=${encodeURIComponent(similar.name)}`,
            },
        playbackContext: similar.in_library
          ? { artist: similar.name }
          : undefined,
      }));

    return [
      {
        id: 'similar-artists',
        title: 'Similar Artists',
        entityType: 'artist' as const,
        items: similarArtistItems,
        layout: 'list' as const,
      },
    ];
  }, [artist, limit]);

  return {
    sections,
    hasDiscovery: sections.some((s) => s.items.length > 0),
  };
}
