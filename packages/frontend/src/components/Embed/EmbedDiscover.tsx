import { lazy, Suspense, useCallback, useRef } from 'react';
import { Loader2 } from 'lucide-react';
import { ScrollContainerContext } from '../../hooks/useScrollContainer';
import { postNavigateIntent, postPlayIntent } from '../../services/embedBridge';

const DiscoverSurface = lazy(() => import('./DiscoverSurface'));

/**
 * Discover, alone, for the embedded surface (ADR-0016 point 2, ADR-0017).
 *
 * This file is the boundary between a large web surface and a native app, and ADR-0016 names that
 * seam as the main risk of embedding at all. It used to guard the seam by supplying all
 * twenty-four `BrowserProps` fields — most of them empty — so a field `DiscoverBrowser` started
 * reading was a type error here rather than `undefined` inside a web view.
 *
 * ADR-0081 point 5 replaced that with the two fields the surface actually reads. The guard survives
 * and moves: reading a third is now a compile error in `DiscoverSurface` itself. What is gone is
 * twenty-two empty values standing in for a registry that no longer exists.
 */
export function EmbedDiscover() {
  const scrollRef = useRef<HTMLDivElement>(null);

  /**
   * A play button in Discover posts to the native player and does nothing else.
   *
   * Discover hands over one track id, so the intent is a queue of one. That is honest — it is what
   * was asked for — rather than inventing surrounding context the surface never offered.
   */
  const handlePlayTrack = useCallback((trackId: string) => {
    postPlayIntent({ trackIds: [trackId], startingAt: trackId });
  }, []);

  const handleGoToArtist = useCallback((artistName: string) => {
    postNavigateIntent({ to: 'artist', artist: artistName });
  }, []);


  /**
   * Two fields, both handed to the *app* rather than followed in the page (ADR-0020).
   *
   * `onGoToAlbum`, and the year/genre/mood navigations, used to be supplied here as well — the
   * album one live, the rest inert because the native app has no screen for a year, a genre or a
   * mood region, and a message leading nowhere would be worse than a link that does nothing.
   * `DiscoverSurface` reads neither, so they are gone rather than passed and ignored.
   */
  const props = {
    onGoToArtist: handleGoToArtist,
    onPlayTrack: handlePlayTrack,
  };

  return (
    // **A real scroll container, and a bounded one.** `PlaylistTrackList` virtualises its rows
    // against whichever element `useScrollContainer` hands it, falling back to its own
    // `flex-1 min-h-0 overflow-y-auto` wrapper when there is no provider. Neither worked here: the
    // embed had no provider *and* no height-bounded flex column, so the fallback measured zero and
    // the virtualiser rendered zero rows. "Unheard in Your Library" and "Deep Cuts" drew their
    // headers, their counts, and nothing else — not even the empty message, because the lists were
    // not empty.
    //
    // The card grids above them were unaffected, which is what made it look like a data problem
    // rather than a layout one.
    //
    // `h-screen` + `flex flex-col` gives the definite height the chain needs, and providing the
    // context makes the embedded page scroll as one surface, exactly as `AppShell` does for the app.
    <div className="h-screen flex flex-col bg-zinc-900 text-zinc-100">
      <ScrollContainerContext.Provider value={scrollRef}>
        <div ref={scrollRef} className="flex-1 overflow-y-auto overflow-x-hidden min-h-0">
          <Suspense fallback={<EmbedLoading />}>
            <DiscoverSurface {...props} />
          </Suspense>
        </div>
      </ScrollContainerContext.Provider>
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


