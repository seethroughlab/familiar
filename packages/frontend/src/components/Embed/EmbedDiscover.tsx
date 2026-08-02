import { lazy, Suspense, useCallback } from 'react';
import { Loader2 } from 'lucide-react';
import type { BrowserProps, LibraryFilters } from '../Library/types';
import { postPlayIntent } from '../../services/embedBridge';

// Imported directly rather than through `browsers/index.ts`, which registers all nine and would pull
// the track list, the album grid and the Music Map into a bundle that shows none of them.
const DiscoverBrowser = lazy(() => import('../Library/browsers/DiscoverBrowser/DiscoverBrowser'));

/**
 * Discover, alone, for the embedded surface (ADR-0016 point 2, ADR-0017).
 *
 * `DiscoverBrowser` takes the full `BrowserProps` because every library browser does, and reads two
 * of its twenty-two fields. The rest are supplied empty here rather than cast away, so that a field
 * it starts reading later is a type error at this seam instead of `undefined` at runtime — this file
 * is the boundary between a 2,943-line surface and a native app, and ADR-0016 names that seam as the
 * main risk of embedding at all.
 */
export function EmbedDiscover() {
  /**
   * A play button in Discover posts to the native player and does nothing else.
   *
   * Discover hands over one track id, so the intent is a queue of one. That is honest — it is what
   * was asked for — rather than inventing surrounding context the surface never offered.
   */
  const handlePlayTrack = useCallback((trackId: string) => {
    postPlayIntent({ trackIds: [trackId], startingAt: trackId });
  }, []);

  const props: BrowserProps = {
    tracks: [],
    artists: [],
    albums: [],
    isLoading: false,

    // Selection exists to build playlists out of a track list. There is no track list here.
    selectedTrackIds: new Set<string>(),
    onSelectTrack: noop,
    onSelectAll: noop,
    onClearSelection: noop,

    // Navigation is the open question ADR-0017 leaves as a follow-up: this surface renders Discover
    // and has nowhere else to go, so these are inert rather than routes to blank screens. The router
    // in `renderEmbed` sends any internal navigation back here for the same reason.
    onGoToArtist: noop,
    onGoToAlbum: noop,
    onGoToYear: noop,
    onGoToYearRange: noop,
    onGoToGenre: noop,
    onGoToMood: noop,

    onPlayTrack: handlePlayTrack,
    // Discover has no index to play at, and queueing is a native-side concept here — the bridge is
    // one message wide (ADR-0016 point 5) and "play" is that message.
    onPlayTrackAt: (trackId: string) => handlePlayTrack(trackId),
    onQueueTrack: noop,

    onEditTrack: noop,

    filters: EMPTY_FILTERS,
    onFilterChange: noop,
  };

  return (
    <div className="min-h-screen bg-zinc-900 text-zinc-100">
      <Suspense fallback={<EmbedLoading />}>
        <DiscoverBrowser {...props} />
      </Suspense>
    </div>
  );
}

function EmbedLoading() {
  return (
    <div role="status" aria-label="Loading" className="flex items-center justify-center py-20">
      <Loader2 className="w-8 h-8 animate-spin text-zinc-400" />
    </div>
  );
}

function noop() {}

// Every field on `LibraryFilters` is optional, so this needs no cast — which is the point of
// building the props out rather than asserting them.
const EMPTY_FILTERS: LibraryFilters = {};
