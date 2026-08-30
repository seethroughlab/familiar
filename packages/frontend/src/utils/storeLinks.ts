/**
 * Music store search URL generation.
 * Frontend mirror of backend/app/services/search_links.py
 */

const STORES: Record<string, { name: string; urlTemplate: string }> = {
  bandcamp: {
    name: 'Bandcamp',
    urlTemplate: 'https://bandcamp.com/search?q={query}',
  },
  discogs: {
    name: 'Discogs',
    urlTemplate: 'https://www.discogs.com/search/?q={query}&type=all',
  },
  qobuz: {
    name: 'Qobuz',
    urlTemplate: 'https://www.qobuz.com/search?q={query}',
  },
  '7digital': {
    name: '7digital',
    urlTemplate: 'https://www.7digital.com/search?q={query}',
  },
  itunes: {
    name: 'iTunes',
    urlTemplate: 'https://music.apple.com/search?term={query}',
  },
  amazon: {
    name: 'Amazon Music',
    urlTemplate: 'https://www.amazon.com/s?k={query}&i=digital-music',
  },
};

export const DEFAULT_STORE = 'bandcamp';
export const STORE_ORDER = ['bandcamp', 'discogs', 'qobuz', '7digital', 'itunes', 'amazon'];

// Store icons/colors for visual distinction in UI pills
export const STORE_STYLES: Record<string, { color: string; abbrev: string }> = {
  bandcamp: { color: 'bg-teal-600 hover:bg-teal-500', abbrev: 'BC' },
  discogs: { color: 'bg-orange-600 hover:bg-orange-500', abbrev: 'DC' },
  qobuz: { color: 'bg-blue-600 hover:bg-blue-500', abbrev: 'QB' },
  '7digital': { color: 'bg-purple-600 hover:bg-purple-500', abbrev: '7D' },
  itunes: { color: 'bg-pink-600 hover:bg-pink-500', abbrev: 'IT' },
  amazon: { color: 'bg-warning-strong hover:bg-warning-strong', abbrev: 'AZ' },
};

export function generateSearchUrl(storeKey: string, artist: string, title: string, album?: string): string | null {
  const store = STORES[storeKey];
  if (!store) return null;
  const parts = [artist, title];
  if (album) parts.push(album);
  const query = encodeURIComponent(parts.join(' '));
  return store.urlTemplate.replace('{query}', query);
}

export function generateAllSearchUrls(artist: string, title: string, album?: string): Array<{ key: string; name: string; url: string }> {
  return STORE_ORDER.map((key) => {
    const url = generateSearchUrl(key, artist, title, album);
    return url ? { key, name: STORES[key].name, url } : null;
  }).filter((x): x is { key: string; name: string; url: string } => x !== null);
}
