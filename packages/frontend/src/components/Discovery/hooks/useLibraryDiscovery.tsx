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

    // Section 1: rediscovery — owned, unheard, ranked against real listening.
    //
    // Replaces the old "Unheard in Your Library" and "Deep Cuts", which were
    // `ORDER BY random()` over tracks by artists already played. The subtitle now
    // carries *why* each track is here — a real played track, not a generated label
    // (ADR-0101 point 3, inherited from ADR-0093's three failed attempts at naming a
    // cluster).
    if (data.rediscovery && data.rediscovery.length > 0) {
      const items: DiscoveryItem[] = data.rediscovery.map((s) => ({
        id: s.track.id,
        entityType: 'track' as const,
        name: s.track.title || 'Unknown Track',
        subtitle: s.because_of_title
          ? `${s.track.artist || 'Unknown Artist'} · because you play ${s.because_of_title}`
          : s.track.artist || 'Unknown Artist',
        inLibrary: true,
        playbackContext: {
          artist: s.track.artist || '',
          album: s.track.album || undefined,
          trackId: s.track.id,
        },
      }));

      sections.push({
        id: 'rediscovery',
        title: 'In Your Library, Unheard',
        description: 'Ranked against what you actually listen to',
        entityType: 'track',
        items,
        layout: 'tracklist',
        rawTracks: data.rediscovery.map((s) => s.track),
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
          amazon: `https://www.amazon.com/s?k=${encodeURIComponent(artist.name)}&i=digital-music`,
          apple: `https://music.apple.com/us/search?term=${encodeURIComponent(artist.name)}`,
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
