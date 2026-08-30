/**
 * DiscoverBrowser - Music discovery dashboard.
 *
 * Sections (top to bottom):
 * - Curated prompts (LLM)
 * - New releases from your artists (#3)
 * - Albums you might want (listening-profile #2)
 * - Unheard tracks by your top artists (existing)
 * - Deep cuts (existing)
 * - External artists to explore (existing)
 */
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  Music,
  Loader2,
} from 'lucide-react';
import { libraryApi } from '../../api';
import { queryKeys } from '../../api/queryKeys';
import { STALE_TIME } from '../../api/queryDefaults';
import { useOfflineStatus } from '../../hooks/useOfflineStatus';
import {
  useLibraryDiscovery,
  DiscoverySectionView,
  type DiscoveryItem,
} from '../Discovery';
import { NewReleasesSection } from './NewReleasesSection';
import { ListeningProfileSection } from './ListeningProfileSection';


/**
 * Discover, as the Apple clients embed it (ADR-0016 point 2, ADR-0017).
 *
 * **Was `DiscoverBrowser`, registered in a browser registry ADR-0081 point 3 deleted.** The registry
 * ended with one member whose only consumer imported it directly, which is indirection with nothing
 * on the other end. The file now lives beside `EmbedDiscover`, the only thing that renders it.
 *
 * **Its props are the two fields it reads, not the twenty-four a "browser" used to take** (point 5).
 * `EmbedDiscover` previously supplied every field, most of them empty, so that a field this
 * component started reading would be a type error at the seam rather than `undefined` inside a web
 * view. That protection is kept and improves: reading a third field is now a compile error *here*,
 * at the definition, instead of depending on the caller having pre-supplied it.
 */
export interface DiscoverSurfaceProps {
  /** Open an artist. In the embed this posts a navigate intent to the native app. */
  onGoToArtist: (artistName: string) => void;
  /** Play one track. In the embed this posts a play intent; it never starts an audio engine. */
  onPlayTrack: (trackId: string) => void;
}

export default function DiscoverSurface({ onGoToArtist, onPlayTrack }: DiscoverSurfaceProps) {
  const discoverNavigate = useNavigate();
  const { isOffline } = useOfflineStatus();

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: queryKeys.libraryDiscover.all,
    queryFn: () =>
      libraryApi.getDiscover({
        recommendations_limit: 12,
        seed_artists: 10,
        similar_per_artist: 8,
      }),
    enabled: !isOffline,
    staleTime: STALE_TIME.LONG,
  });


  const { sections } = useLibraryDiscovery({ data });

  if (isOffline) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-zinc-500 gap-2 p-6 text-center">
        <p className="text-zinc-300">Discovery is not available offline.</p>
        <p className="text-sm">Reconnect to load recommendations and new releases.</p>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-zinc-400" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-zinc-500 gap-3">
        <p>Unable to load discovery data. Check your connection and try again.</p>
        <button
          onClick={() => refetch()}
          className="px-3 py-1.5 text-sm bg-zinc-700 hover:bg-zinc-600 rounded-md text-zinc-300"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-zinc-400" />
      </div>
    );
  }

  const { recently_added_count } = data;

  const handleGoToArtist = (artistName: string) => {
    if (onGoToArtist) {
      onGoToArtist(artistName);
    } else {
      discoverNavigate(`/library/artists/${encodeURIComponent(artistName)}`);
    }
  };

  const handleItemClick = (item: DiscoveryItem) => {
    if (item.inLibrary && item.entityType === 'artist') {
      handleGoToArtist(item.name);
    }
  };

  const handleItemPlay = (item: DiscoveryItem) => {
    if (item.playbackContext?.trackId) {
      onPlayTrack(item.playbackContext.trackId);
    }
  };

  return (
    <div className="h-full overflow-y-auto p-4 space-y-8">
      {/* AI-generated listening suggestions */}

      {/* External-album sections (Pass 3) — placed above existing sections
          since "what's new" / "what to acquire" are more actionable than
          "deep cuts in your library". */}
      <NewReleasesSection />
      <ListeningProfileSection />

      {/* Stats banner */}
      {recently_added_count > 0 && (
        <div className="flex gap-4 text-sm text-zinc-400">
          <span className="flex items-center gap-1">
            <Music className="w-4 h-4" />
            {recently_added_count} tracks added recently
          </span>
        </div>
      )}

      {/* Existing in-library Discovery sections */}
      {sections.map((section) => (
        <section key={section.id}>
          <DiscoverySectionView
            section={section}
            showHeader={true}
            gridColumns={6}
            onItemClick={handleItemClick}
            onItemPlay={handleItemPlay}
          />
        </section>
      ))}
    </div>
  );
}
