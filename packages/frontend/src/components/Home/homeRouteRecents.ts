import type { RecentDestination } from '../../stores/homeStore';

function decodeSegment(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

export function classifyRecentDestination(pathname: string): Omit<RecentDestination, 'timestamp'> | null {
  if (!pathname || pathname === '/' || pathname === '/home' || pathname === '/admin') {
    return null;
  }

  if (pathname === '/favorites') {
    return { route: pathname, label: 'Favorites', type: 'favorites' };
  }
  if (pathname === '/downloads') {
    return { route: pathname, label: 'Downloads', type: 'downloads' };
  }
  if (pathname === '/library/discover') {
    return { route: pathname, label: 'Discover', type: 'discover' };
  }

  const browserLabels: Record<string, string> = {
    '/library/tracks': 'Tracks',
    '/library/artists': 'Artists',
    '/library/albums': 'Albums',
    '/library/mood-grid': 'Mood Grid',
    '/library/music-map': 'Music Map',
    '/library/explorer': '3D Explorer',
    '/library/proposed-changes': 'Changes',
    '/library/pending-review': 'Review',
    '/library/spotify': 'Spotify Library',
  };
  if (browserLabels[pathname]) {
    return { route: pathname, label: browserLabels[pathname], type: 'browser' };
  }

  const artistMatch = pathname.match(/^\/library\/artists\/(.+)$/);
  if (artistMatch) {
    const artistName = decodeSegment(artistMatch[1]);
    return {
      route: pathname,
      label: artistName,
      subtitle: 'Artist',
      type: 'artist',
    };
  }

  const albumMatch = pathname.match(/^\/library\/albums\/([^/]+)\/(.+)$/);
  if (albumMatch) {
    const artist = decodeSegment(albumMatch[1]);
    const album = decodeSegment(albumMatch[2]);
    return {
      route: pathname,
      label: album,
      subtitle: artist,
      type: 'album',
    };
  }

  const playlistMatch = pathname.match(/^\/playlists\/([^/]+)$/);
  if (playlistMatch) {
    return {
      route: pathname,
      label: `Playlist ${playlistMatch[1]}`,
      subtitle: 'Playlist',
      type: 'playlist',
    };
  }

  const smartPlaylistMatch = pathname.match(/^\/smart-playlists\/([^/]+)$/);
  if (smartPlaylistMatch) {
    return {
      route: pathname,
      label: `Smart Playlist ${smartPlaylistMatch[1]}`,
      subtitle: 'Smart Playlist',
      type: 'smart-playlist',
    };
  }

  return null;
}
