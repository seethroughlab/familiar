import { useMemo } from 'react';
import type { DiscoverySection, DiscoveryItem } from '../types';

// Other album by artist (doesn't have similarity_score)
interface OtherAlbumInfo {
  name: string;
  artist: string;
  year: number | null;
  track_count: number;
  first_track_id: string;
}

// Similar album (has similarity_score)
interface SimilarAlbumInfo {
  name: string;
  artist: string;
  year: number | null;
  track_count: number;
  first_track_id: string;
  similarity_score: number;
}

// Discover album (external)
interface DiscoverAlbumInfo {
  name: string;
  artist: string;
  image_url: string | null;
  lastfm_url: string | null;
  bandcamp_url: string | null;
}

// Partial type for the fields we need from AlbumDetailResponse
interface AlbumDiscoveryData {
  artist: string;
  other_albums_by_artist?: OtherAlbumInfo[];
  similar_albums?: SimilarAlbumInfo[];
  discover_albums?: DiscoverAlbumInfo[];
}

interface UseAlbumDiscoveryOptions {
  album: AlbumDiscoveryData | null | undefined;
}

interface UseAlbumDiscoveryResult {
  sections: DiscoverySection[];
  hasDiscovery: boolean;
}

/**
 * Transform album detail data into discovery sections
 *
 * Returns two sections:
 * - "More from {Artist}" - other albums by the same artist
 * - "Similar Albums" - similar albums from library + external discovery
 */
export function useAlbumDiscovery({ album }: UseAlbumDiscoveryOptions): UseAlbumDiscoveryResult {
  const sections = useMemo(() => {
    if (!album) return [];

    const result: DiscoverySection[] = [];

    // Section 1: More from artist
    if (album.other_albums_by_artist && album.other_albums_by_artist.length > 0) {
      const moreFromArtistItems: DiscoveryItem[] = album.other_albums_by_artist.map(
        (other: OtherAlbumInfo) => ({
          id: other.first_track_id,
          entityType: 'album' as const,
          name: other.name,
          subtitle: other.year
            ? `${other.year} \u00B7 ${other.track_count} tracks`
            : `${other.track_count} tracks`,
          inLibrary: true,
          playbackContext: {
            artist: other.artist,
            album: other.name,
            trackId: other.first_track_id,
          },
        })
      );

      result.push({
        id: 'more-from-artist',
        title: `More from ${album.artist}`,
        entityType: 'album',
        items: moreFromArtistItems,
        layout: 'list',
      });
    }

    // Section 2: Similar albums (library + external)
    const similarAlbumItems: DiscoveryItem[] = [];

    // Add similar albums from library
    if (album.similar_albums) {
      album.similar_albums.forEach((similar: SimilarAlbumInfo) => {
        similarAlbumItems.push({
          id: similar.first_track_id,
          entityType: 'album',
          name: similar.name,
          subtitle: similar.artist,
          matchScore: similar.similarity_score,
          inLibrary: true,
          playbackContext: {
            artist: similar.artist,
            album: similar.name,
            trackId: similar.first_track_id,
          },
        });
      });
    }

    // Add discover albums (external)
    if (album.discover_albums) {
      album.discover_albums.forEach((discover: DiscoverAlbumInfo) => {
        similarAlbumItems.push({
          entityType: 'album',
          name: discover.name,
          subtitle: discover.artist,
          imageUrl: discover.image_url || undefined,
          inLibrary: false,
          externalLinks: {
            bandcamp: discover.bandcamp_url || undefined,
            lastfm: discover.lastfm_url || undefined,
          },
        });
      });
    }

    if (similarAlbumItems.length > 0) {
      result.push({
        id: 'similar-albums',
        title: 'Similar Albums',
        entityType: 'album',
        items: similarAlbumItems,
        layout: 'list',
      });
    }

    return result;
  }, [album]);

  return {
    sections,
    hasDiscovery: sections.some((s) => s.items.length > 0),
  };
}
