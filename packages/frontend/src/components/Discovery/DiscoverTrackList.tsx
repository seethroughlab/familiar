import { useCallback } from 'react';
import { usePlayerStore } from '../../stores/playerStore';
import { PlaylistTrackList, type TrackRowContext } from '../shared/PlaylistTrackList';
import { formatDuration } from '../../utils/format';
import type { Track } from '../../types';
import type { DiscoverTrack } from '../../api';

interface Props {
  items: DiscoverTrack[];
  sortPersistKey: string;
}

export function DiscoverTrackList({ items, sortPersistKey }: Props) {
  const setQueueByTrackId = usePlayerStore((s) => s.setQueueByTrackId);
  const currentTrack = usePlayerStore((s) => s.currentTrack);
  const isPlaying = usePlayerStore((s) => s.isPlaying);
  const setIsPlaying = usePlayerStore((s) => s.setIsPlaying);

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
      if (currentTrack?.id === track.id) {
        setIsPlaying(!isPlaying);
        return;
      }

      setQueueByTrackId(list.map(getTrack), track.id);
    },
    [items, getTrack, currentTrack?.id, isPlaying, setIsPlaying, setQueueByTrackId],
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
