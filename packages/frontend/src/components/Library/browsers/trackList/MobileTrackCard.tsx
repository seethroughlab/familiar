/**
 * Mobile card component for track list display on small screens.
 * Supports long-press for context menu and drag for playlist creation.
 */
import { useLongPress } from '../../../../hooks/useLongPress';
import { MobilePlayIndicator } from '../../../common/PlayIndicator';
import { FavoriteButton } from './FavoriteButton';
import { OfflineButton } from './OfflineButton';
import type { Track } from '../../../../types';

export interface MobileTrackCardProps {
  track: Track;
  index: number;
  isCurrentTrack: boolean;
  isPlaying: boolean;
  isSelected: boolean;
  onPlay: () => void;
  onClick: (e: React.MouseEvent) => void;
  onContextMenu: (e: React.MouseEvent) => void;
  onLongPress: (position: { x: number; y: number }) => void;
}

export function MobileTrackCard({
  track,
  index,
  isCurrentTrack,
  isPlaying,
  isSelected,
  onPlay,
  onClick,
  onContextMenu,
  onLongPress,
}: MobileTrackCardProps) {
  const formatDuration = (seconds: number | null) => {
    if (!seconds) return '--:--';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const longPressHandlers = useLongPress(onLongPress);

  return (
    <div
      data-testid="track-row"
      data-list-index={index}
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData('application/track-id', track.id);
        e.dataTransfer.effectAllowed = 'copy';
      }}
      onClick={onClick}
      onContextMenu={onContextMenu}
      {...longPressHandlers}
      className={`group flex items-center gap-3 px-4 py-3 cursor-pointer border-b border-zinc-800/30 ${
        isSelected
          ? 'bg-purple-500/20'
          : isCurrentTrack
          ? 'bg-zinc-800/50'
          : 'hover:bg-zinc-800/50'
      }`}
    >
      {/* Play button / index - show play icon on mobile when selected, number otherwise */}
      <button
        onClick={(e) => { e.stopPropagation(); onPlay(); }}
        className="w-8 flex-shrink-0 flex items-center justify-center text-zinc-400"
      >
        <MobilePlayIndicator isCurrent={isCurrentTrack} isPlaying={isPlaying} isSelected={isSelected} index={index + 1} />
      </button>

      {/* Track info */}
      <div className="flex-1 min-w-0">
        <div className={`truncate font-medium flex items-center gap-1.5 ${isCurrentTrack ? 'text-green-500' : 'text-white'}`}>
          <span className="truncate">{track.title || 'Unknown'}</span>
        </div>
        <div className="text-sm text-zinc-400 truncate">
          {track.artist || 'Unknown Artist'}
          {track.album && <span className="text-zinc-500"> • {track.album}</span>}
        </div>
      </div>

      {/* Duration */}
      <div className="text-sm text-zinc-400 flex-shrink-0">
        {formatDuration(track.duration_seconds)}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-1 flex-shrink-0">
        <FavoriteButton trackId={track.id} />
        <OfflineButton trackId={track.id} />
      </div>
    </div>
  );
}
