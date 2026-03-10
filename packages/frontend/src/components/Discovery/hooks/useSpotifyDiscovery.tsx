import { useMemo } from 'react';
import type { DiscoverySection, DiscoveryItem } from '../types';
import type { SpotifyImportData, SpotifyTrack } from '../../../api/spotify';

type MatchFilter = 'all' | 'matched' | 'missing';

interface UseSpotifyDiscoveryOptions {
  data: SpotifyImportData | null | undefined;
  tab: 'favorites' | 'playlists' | 'stats';
  matchFilter: MatchFilter;
}

interface UseSpotifyDiscoveryResult {
  sections: DiscoverySection[];
  hasContent: boolean;
}

function normalizeForKey(s: string): string {
  return s
    .replace(/\s*[([](feat\.?|ft\.?|featuring)[^)\]]*[)\]]/gi, '')
    .replace(/\s*[([][^)\]]*(?:remaster(?:ed)?|remix|version|edit|deluxe|bonus)[^)\]]*[)\]]/gi, '')
    .replace(/\u2018/g, "'")
    .replace(/\u2019/g, "'")
    .replace(/`/g, "'")
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
}

function makeMatchKey(artist: string, track: string): string {
  return `${normalizeForKey(artist)}:${normalizeForKey(track)}`;
}

function spotifyTrackToDiscoveryItem(
  t: SpotifyTrack,
  matchResults: Record<string, { track_id: string; method: string; confidence: number }>,
): DiscoveryItem {
  const key = makeMatchKey(t.artist, t.track);
  const match = matchResults[key];
  return {
    id: match?.track_id,
    entityType: 'track' as const,
    name: t.track || 'Unknown Track',
    subtitle: t.artist || 'Unknown Artist',
    inLibrary: !!match,
    matchScore: match?.confidence,
    playbackContext: match
      ? { artist: t.artist, album: t.album || undefined, trackId: match.track_id }
      : undefined,
    externalLinks: match ? undefined : {
      spotify: t.uri
        ? `https://open.spotify.com/track/${t.uri.replace('spotify:track:', '')}`
        : undefined,
      bandcamp: `https://bandcamp.com/search?q=${encodeURIComponent(`${t.artist} ${t.track}`)}`,
      lastfm: `https://www.last.fm/music/${encodeURIComponent(t.artist)}/_/${encodeURIComponent(t.track)}`,
    },
  };
}

function filterItems(items: DiscoveryItem[], filter: MatchFilter): DiscoveryItem[] {
  if (filter === 'matched') return items.filter((i) => i.inLibrary);
  if (filter === 'missing') return items.filter((i) => !i.inLibrary);
  return items;
}

export function useSpotifyDiscovery({
  data,
  tab,
  matchFilter,
}: UseSpotifyDiscoveryOptions): UseSpotifyDiscoveryResult {
  return useMemo(() => {
    if (!data) return { sections: [], hasContent: false };

    const sections: DiscoverySection[] = [];
    const mr = data.match_results;

    if (tab === 'favorites') {
      const items = filterItems(
        data.favorites.map((t) => spotifyTrackToDiscoveryItem(t, mr)),
        matchFilter,
      );
      sections.push({
        id: 'spotify-favorites',
        title: 'Saved Tracks',
        description: `${data.summary.matched_favorites} of ${data.summary.total_favorites} in library`,
        entityType: 'track',
        items,
        layout: 'list',
      });
    }

    if (tab === 'playlists') {
      for (const pl of data.playlists) {
        const items = filterItems(
          pl.items.map((t) => spotifyTrackToDiscoveryItem(t, mr)),
          matchFilter,
        );
        if (items.length === 0) continue;
        const matchedCount = pl.items.filter((t) => {
          const key = makeMatchKey(t.artist, t.track);
          return !!mr[key];
        }).length;
        sections.push({
          id: `spotify-playlist-${pl.name}`,
          title: pl.name,
          description: `${matchedCount}/${pl.track_count} in library`,
          entityType: 'track',
          items,
          layout: 'list',
        });
      }
    }

    if (tab === 'stats') {
      // Top tracks by listen time
      const topTrackItems = filterItems(
        data.streaming_stats.top_tracks.map((t) => {
          const key = makeMatchKey(t.artist, t.track);
          const match = mr[key];
          const hours = Math.round(t.ms_played / 3600000 * 10) / 10;
          return {
            id: match?.track_id,
            entityType: 'track' as const,
            name: t.track,
            subtitle: `${t.artist} · ${hours}h`,
            inLibrary: !!match,
            matchScore: match?.confidence,
            playbackContext: match
              ? { artist: t.artist, trackId: match.track_id }
              : undefined,
            externalLinks: match ? undefined : {
              bandcamp: `https://bandcamp.com/search?q=${encodeURIComponent(`${t.artist} ${t.track}`)}`,
              lastfm: `https://www.last.fm/music/${encodeURIComponent(t.artist)}/_/${encodeURIComponent(t.track)}`,
            },
          };
        }),
        matchFilter,
      );
      if (topTrackItems.length > 0) {
        sections.push({
          id: 'spotify-top-tracks',
          title: 'Most Played Tracks',
          entityType: 'track',
          items: topTrackItems,
          layout: 'list',
        });
      }

      // Top artists by listen time (only show for 'all' or 'matched' filter, skip for 'missing')
      if (matchFilter !== 'missing') {
        const topArtistItems: DiscoveryItem[] = data.streaming_stats.top_artists
          .slice(0, 30)
          .map((a) => {
            const hours = Math.round(a.ms_played / 3600000 * 10) / 10;
            return {
              entityType: 'artist' as const,
              name: a.artist,
              subtitle: `${hours}h listened`,
              inLibrary: true, // We don't track artist-level matching
            };
          });
        if (topArtistItems.length > 0) {
          sections.push({
            id: 'spotify-top-artists',
            title: 'Most Played Artists',
            entityType: 'artist',
            items: topArtistItems,
            layout: 'grid',
          });
        }
      }
    }

    return {
      sections,
      hasContent: sections.some((s) => s.items.length > 0),
    };
  }, [data, tab, matchFilter]);
}
