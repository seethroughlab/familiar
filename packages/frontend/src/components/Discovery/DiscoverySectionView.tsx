import { Disc, Disc3, User } from 'lucide-react';
import type { DiscoverySection, DiscoveryItem } from './types';
import { useSyncExternalStore } from 'react';
import { getNowPlaying, subscribeToNowPlaying } from '../../services/nowPlayingSink';
import { DiscoveryList } from './DiscoveryList';
import { DiscoveryGrid } from './DiscoveryGrid';
import { DiscoverTrackList } from './DiscoverTrackList';

interface DiscoverySectionViewProps {
  section: DiscoverySection;
  onItemClick?: (item: DiscoveryItem) => void;
  onItemPlay?: (item: DiscoveryItem) => void;
  showHeader?: boolean;
  gridColumns?: 2 | 3 | 4 | 5 | 6;
  className?: string;
}

/**
 * Get the default icon for an entity type
 */
function getTypeIcon(entityType: 'album' | 'artist' | 'track') {
  switch (entityType) {
    case 'artist':
      return <User className="w-5 h-5 text-zinc-400" />;
    case 'track':
      return <Disc3 className="w-5 h-5 text-zinc-400" />;
    default:
      return <Disc className="w-5 h-5 text-zinc-400" />;
  }
}

/**
 * Renders a single discovery section with optional header
 */
export function DiscoverySectionView({
  section,
  onItemClick,
  onItemPlay,
  showHeader = true,
  gridColumns = 4,
  className = '',
}: DiscoverySectionViewProps) {
  /**
   * What the native app is playing (ADR-0090).
   *
   * **Read here, one level above the three components that draw it**, because ADR-0083 point 1 puts
   * playing state on their props: this is the parent that knows, and they stay prop-driven and
   * testable without a channel. In the web app nothing ever calls the sink, so this is
   * `{ null, false }` for the life of the page and no row is marked — correct rather than degraded,
   * since that app has no player.
   */
  const nowPlaying = useSyncExternalStore(subscribeToNowPlaying, getNowPlaying);

  if (section.items.length === 0) {
    return null;
  }

  const layout = section.layout || 'list';

  return (
    <div className={className}>
      {showHeader && (
        <div className="mb-3">
          <div className="flex items-center gap-2">
            {section.icon || getTypeIcon(section.entityType)}
            <h2 className="text-lg font-semibold text-zinc-100">{section.title}</h2>
            <span className="px-2 py-0.5 text-xs rounded-full bg-zinc-800 text-zinc-400">
              {section.items.length}
            </span>
          </div>
          {section.description && (
            <p className="text-xs text-zinc-500 mt-1 ml-7">{section.description}</p>
          )}
        </div>
      )}

      {layout === 'tracklist' && section.rawTracks ? (
        <DiscoverTrackList
          items={section.rawTracks}
          sortPersistKey={`discover-${section.id}`}
          currentTrackId={nowPlaying.trackId}
          isPlaying={nowPlaying.playing}
          /*
           * **Play went nowhere without this.** `DiscoverTrackList` stopped reaching into
           * `playerStore` under ADR-0083 and started taking a callback instead — but this parent
           * was never updated to pass one, and `onPlayTracks?.()` swallowed every click. The two
           * layouts either side of this branch were wired all along, so it failed only in the
           * `tracklist` sections: "Unheard in Your Library" and "Deep Cuts".
           *
           * A track id is all the embedded surface can act on — it posts an intent for a queue of
           * one (ADR-0016 point 4, ADR-0090 point 4), so the list is deliberately not forwarded.
           */
          onPlayTracks={
            onItemPlay
              ? (_tracks, startId) => {
                  const item = section.items.find((i) => i.playbackContext?.trackId === startId);
                  if (item) onItemPlay(item);
                }
              : undefined
          }
        />
      ) : layout === 'grid' ? (
        <DiscoveryGrid
          items={section.items}
          columns={gridColumns}
          onItemClick={onItemClick}
          onItemPlay={onItemPlay}
          currentTrackId={nowPlaying.trackId}
          isPlaying={nowPlaying.playing}
        />
      ) : (
        <DiscoveryList
          items={section.items}
          onItemClick={onItemClick}
          onItemPlay={onItemPlay}
          currentTrackId={nowPlaying.trackId}
          isPlaying={nowPlaying.playing}
        />
      )}
    </div>
  );
}
