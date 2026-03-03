import { useMemo } from 'react';
import type { DiscoverySection, DiscoveryItem } from '../types';
import type { PlaylistRecommendations } from '../../../api';

interface UsePlaylistDiscoveryOptions {
  recommendations: PlaylistRecommendations | null | undefined;
}

interface UsePlaylistDiscoveryResult {
  sections: DiscoverySection[];
  sources: string[];
  hasDiscovery: boolean;
}

/**
 * Transform playlist recommendations into discovery sections
 *
 * Returns two sections:
 * - "Artists" - recommended artists based on playlist content
 * - "Tracks" - recommended tracks based on playlist content
 */
export function usePlaylistDiscovery({
  recommendations,
}: UsePlaylistDiscoveryOptions): UsePlaylistDiscoveryResult {
  const result = useMemo(() => {
    if (!recommendations) {
      return {
        sections: [],
        sources: [],
        hasDiscovery: false,
      };
    }

    const sections: DiscoverySection[] = [];

    // Section 1: Artists
    if (recommendations.artists && recommendations.artists.length > 0) {
      const artistItems: DiscoveryItem[] = recommendations.artists.map((artist) => ({
        entityType: 'artist' as const,
        name: artist.name,
        subtitle:
          artist.local_track_count > 0
            ? `${artist.local_track_count} tracks in library`
            : 'Not in library',
        imageUrl: artist.image_url || undefined,
        matchScore: artist.match_score,
        inLibrary: artist.local_track_count > 0,
        externalLinks:
          artist.local_track_count > 0
            ? undefined
            : {
                lastfm: artist.external_url || undefined,
              },
        playbackContext:
          artist.local_track_count > 0
            ? { artist: artist.name }
            : undefined,
      }));

      sections.push({
        id: 'artists',
        title: 'Artists',
        entityType: 'artist',
        items: artistItems,
        layout: 'list',
      });
    }

    // Section 2: Tracks
    if (recommendations.tracks && recommendations.tracks.length > 0) {
      const trackItems: DiscoveryItem[] = recommendations.tracks.map((track) => ({
        id: track.local_track_id || undefined,
        entityType: 'track' as const,
        name: track.title,
        subtitle: track.artist,
        matchScore: track.match_score,
        inLibrary: !!track.local_track_id,
        externalLinks: track.local_track_id
          ? undefined
          : {
              lastfm: track.external_url || undefined,
            },
        playbackContext: track.local_track_id
          ? {
              artist: track.artist,
              album: track.album || undefined,
              trackId: track.local_track_id,
            }
          : undefined,
      }));

      sections.push({
        id: 'tracks',
        title: 'Tracks',
        entityType: 'track',
        items: trackItems,
        layout: 'list',
      });
    }

    return {
      sections,
      sources: recommendations.sources_used || [],
      hasDiscovery: sections.some((s) => s.items.length > 0),
    };
  }, [recommendations]);

  return result;
}
