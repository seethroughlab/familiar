import { useCallback } from 'react';
import { PlaylistTrackList, type TrackRowContext } from '../shared/PlaylistTrackList';
import { formatDuration } from '../../utils/format';
import type { Track } from '../../types';
import type { DiscoverTrack } from '../../api';

/**
 * Playing state arrives as props, and starting playback goes out through a callback (ADR-0083
 * points 1 and 2).
 *
 * **This component reached into `playerStore` for all four**, which is why the visualizer and
 * Discover both pinned a 1,016-line queue store, a persistence adapter and IndexedDB behind them —
 * on a surface (`/embed`) where none of it is ever mounted. `setQueueByTrackId` there wrote a queue
 * nothing played from.
 *
 * With the state passed in, *where it comes from* becomes the parent's business: the admin app has
 * no player and passes nothing, while the embedded surface passes what the native app tells it.
 * That is the seam ADR-0016 point 4 is really about — the page never decides what plays.
 */
interface Props {
  items: DiscoverTrack[];
  sortPersistKey: string;
  /** The track the *native* player is on, when the parent knows. */
  currentTrackId?: string | null;
  isPlaying?: boolean;
  /**
   * Play this list, starting here. The parent decides what that means — an intent posted to the
   * app, or nothing at all.
   */
  onPlayTracks?: (tracks: Track[], startId: string) => void;
  /** Toggle the current track. Absent where there is no transport to toggle. */
  onTogglePlay?: () => void;
}

export function DiscoverTrackList({
  items,
  sortPersistKey,
  currentTrackId = null,
  isPlaying = false,
  onPlayTracks,
  onTogglePlay,
}: Props) {

  const getTrack = useCallback(
    (item: DiscoverTrack): Track => ({
      id: item.id,
      file_path: '',
      title: item.title,
      artist: item.artist,
      album: item.album,
      album_artist: null,
      album_type: 'album',
      track_number: null,
      disc_number: null,
      year: null,
      genre: null,
      duration_seconds: item.duration_seconds,
      format: null,
      analysis_version: 0,
      play_count: item.play_count,
    }),
    [],
  );

  const handlePlay = useCallback(
    (startIndex: number, sortedItems?: DiscoverTrack[]) => {
      const list = sortedItems ?? items;
      const item = list[startIndex];
      if (!item) return;

      const track = getTrack(item);
      if (currentTrackId === track.id) {
        onTogglePlay?.();
        return;
      }

      onPlayTracks?.(list.map(getTrack), track.id);
    },
    [items, getTrack, currentTrackId, onTogglePlay, onPlayTracks],
  );

  const getItemId = useCallback((item: DiscoverTrack) => item.id, []);

  const renderDesktopTrailing = useCallback(
    (ctx: TrackRowContext<DiscoverTrack>) => (
      <div className="text-sm text-zinc-500 text-right">
        {formatDuration(ctx.track.duration_seconds)}
      </div>
    ),
    [],
  );

  const renderMobileTrailing = useCallback(
    (ctx: TrackRowContext<DiscoverTrack>) => (
      <div className="flex-shrink-0 text-sm text-zinc-500">
        {formatDuration(ctx.track.duration_seconds)}
      </div>
    ),
    [],
  );

  return (
    <PlaylistTrackList
      items={items}
      currentTrackId={currentTrackId}
      isPlaying={isPlaying}
      getTrack={getTrack}
      getItemId={getItemId}
      onPlay={handlePlay}
      renderDesktopTrailing={renderDesktopTrailing}
      renderMobileTrailing={renderMobileTrailing}
      trailingColumns={['4.5rem']}
      emptyMessage="No tracks found"
      sortPersistKey={sortPersistKey}
      defaultSortBy="artist"
    />
  );
}
