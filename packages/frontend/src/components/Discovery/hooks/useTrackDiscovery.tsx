import { useMemo } from 'react';
import type { DiscoverySection, DiscoveryItem } from '../types';
import { libraryApi } from '../../../api';

// Similar track structure
interface SimilarTrack {
  id: string;
  title: string | null;
  artist: string | null;
  album: string | null;
}

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

// Partial type for the fields we need from TrackDiscoverResponse
interface TrackDiscoveryData {
  similar_tracks?: SimilarTrack[];
  similar_artists?: SimilarArtist[];
}

interface UseTrackDiscoveryOptions {
  data: TrackDiscoveryData | null | undefined;
}

interface UseTrackDiscoveryResult {
  sections: DiscoverySection[];
  hasDiscovery: boolean;
}

/**
 * Transform track discover data into discovery sections
 *
 * Returns two sections:
 * - "Similar Tracks" - tracks similar to the current one
 * - "Similar Artists" - artists similar to the current track's artist
 */
export function useTrackDiscovery({ data }: UseTrackDiscoveryOptions): UseTrackDiscoveryResult {
  const sections = useMemo(() => {
    if (!data) return [];

    const result: DiscoverySection[] = [];

    // Section 1: Similar tracks
    if (data.similar_tracks && data.similar_tracks.length > 0) {
      const trackItems: DiscoveryItem[] = data.similar_tracks.map((track) => ({
        id: track.id,
        entityType: 'track' as const,
        name: track.title || 'Unknown',
        subtitle: track.artist || 'Unknown',
        inLibrary: true,
        playbackContext: {
          artist: track.artist || '',
          album: track.album || undefined,
          trackId: track.id,
        },
      }));

      result.push({
        id: 'similar-tracks',
        title: 'Similar Tracks',
        entityType: 'track',
        items: trackItems,
        layout: 'list',
      });
    }

    // Section 2: Similar artists
    if (data.similar_artists && data.similar_artists.length > 0) {
      const artistItems: DiscoveryItem[] = data.similar_artists.map((artist) => ({
        entityType: 'artist' as const,
        name: artist.name,
        subtitle: artist.in_library
          ? `${artist.track_count} tracks`
          : undefined,
        imageUrl: artist.in_library
          ? libraryApi.getArtistImageUrl(artist.name, 'large')
          : artist.image_url || undefined,
        matchScore: artist.match_score,
        inLibrary: artist.in_library,
        externalLinks: artist.in_library
          ? undefined
          : {
              bandcamp: artist.bandcamp_url || undefined,
              lastfm: artist.lastfm_url || undefined,
              amazon: `https://www.amazon.com/s?k=${encodeURIComponent(artist.name)}&i=digital-music`,
              apple: `https://music.apple.com/us/search?term=${encodeURIComponent(artist.name)}`,
            },
        playbackContext: artist.in_library
          ? { artist: artist.name }
          : undefined,
      }));

      result.push({
        id: 'similar-artists',
        title: 'Similar Artists',
        entityType: 'artist',
        items: artistItems,
        layout: 'list',
      });
    }

    return result;
  }, [data]);

  return {
    sections,
    hasDiscovery: sections.some((s) => s.items.length > 0),
  };
}
