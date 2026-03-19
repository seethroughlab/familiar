/**
 * Desktop virtualized row component for the track list.
 * Renders a single track as a grid row matching the column layout.
 */
import { getColumnDef } from '../../columnDefinitions';
import { PlayIndicator } from '../../../common/PlayIndicator';
import { FavoriteButton } from './FavoriteButton';
import { OfflineButton } from './OfflineButton';
import { usePlayerStore } from '../../../../stores/playerStore';
import type { Track } from '../../../../types';

export interface TrackRowProps {
  track: Track;
  index: number;
  isCurrentTrack: boolean;
  isPlaying: boolean;
  isSelected: boolean;
  onPlay: () => void;
  onClick: (e: React.MouseEvent) => void;
  onDoubleClick: () => void;
  onContextMenu: (e: React.MouseEvent) => void;
  visibleColumnIds: string[];
  gridColumns: string;
}

export function TrackRow({
  track,
  index,
  isCurrentTrack,
  isPlaying,
  isSelected,
  onPlay,
  onClick,
  onDoubleClick,
  onContextMenu,
  visibleColumnIds,
  gridColumns,
}: TrackRowProps) {
  const isLoadingAudio = usePlayerStore((s) => s.isLoadingAudio);
  const loadingClass = isCurrentTrack && isLoadingAudio ? 'animate-pulse bg-green-500/5' : '';

  return (
    <div
      data-testid="track-row"
      data-list-index={index}
      aria-current={isCurrentTrack ? 'true' : undefined}
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData('application/track-id', track.id);
        e.dataTransfer.effectAllowed = 'copy';
      }}
      onClick={onClick}
      onDoubleClick={onDoubleClick}
      onContextMenu={onContextMenu}
      onMouseDown={(e) => {
        // Prevent text selection when using modifier keys for multi-select
        if (e.shiftKey || e.metaKey || e.ctrlKey) {
          e.preventDefault();
        }
      }}
      className={`group grid gap-4 px-4 py-2 rounded-md cursor-pointer select-none ${
        isSelected
          ? 'bg-purple-500/20 hover:bg-purple-500/30'
          : isCurrentTrack
          ? 'bg-zinc-800/50 hover:bg-zinc-800/70'
          : 'hover:bg-zinc-800/50'
      } ${loadingClass}`}
      style={{ gridTemplateColumns: gridColumns }}
    >
      {/* Index / Play button column */}
      <div className="flex items-center justify-center active:scale-90 active:opacity-70 transition-transform duration-75"
        onClick={(e) => { e.stopPropagation(); onPlay(); }}
        onTouchStart={() => {/* iOS :active CSS requires touch listener */}}
        role="button"
        aria-label={isCurrentTrack && isPlaying ? `Pause ${track.title || 'track'}` : `Play ${track.title || 'track'}`}
      >
        <PlayIndicator isCurrent={isCurrentTrack} isPlaying={isPlaying} index={index + 1} />
      </div>

      {/* Title column (always visible) */}
      <div className="min-w-0">
        <div className={`truncate flex items-center gap-1.5 ${isCurrentTrack ? 'text-green-500' : ''}`}>
          {track.title || 'Unknown'}
        </div>
      </div>

      {/* Dynamic columns */}
      {visibleColumnIds.map((colId) => {
        const colDef = getColumnDef(colId);
        if (!colDef) return null;

        const rawValue = colDef.getValue(track);
        const displayValue =
          colDef.format && rawValue != null ? colDef.format(rawValue) : rawValue ?? '-';

        return (
          <div
            key={colId}
            className={`text-zinc-400 truncate ${
              colDef.align === 'right'
                ? 'text-right'
                : colDef.align === 'center'
                ? 'text-center'
                : ''
            }`}
          >
            {displayValue}
          </div>
        );
      })}

      {/* Favorite button */}
      <div className="flex items-center justify-center">
        <FavoriteButton trackId={track.id} />
      </div>

      {/* Offline button */}
      <div className="flex items-center justify-center">
        <OfflineButton trackId={track.id} />
      </div>
    </div>
  );
}
