import { memo, type ReactNode } from 'react';
import { PlayIndicator } from '../common/PlayIndicator';
import { getColumnDef } from '../Library/columnDefinitions';
import { usePlayerStore } from '../../stores/playerStore';
import type { Track } from '../../types';

/** Context passed to render props for each track row. */
export interface TrackRowContext<T> {
  item: T;
  track: Track;
  index: number;
  isCurrentTrack: boolean;
  isPlaying: boolean;
  isSelected: boolean;
}

/** Props for the memoized row component. */
export interface PlaylistRowProps {
  id: string;
  virtualStart: number;
  virtualIndex: number;
  // Track data
  trackId: string;
  trackTitle: string | null;
  trackArtist: string | null;
  trackAlbum: string | null;
  trackDurationSeconds: number | null;
  // State
  isCurrentTrack: boolean;
  isPlaying: boolean;
  isSelected: boolean;
  index: number;
  // Grid
  gridColumns: string;
  visibleColumnIds: string[];
  // Drag
  isDragged: boolean;
  isDropTarget: boolean;
  draggable: boolean;
  extraRowClass: string;
  // Render props (must be stable references)
  renderTitleBadge: ((ctx: TrackRowContext<unknown>) => ReactNode) | undefined;
  renderDragHandle: ((ctx: TrackRowContext<unknown>) => ReactNode) | undefined;
  desktopTrailing: (ctx: TrackRowContext<unknown>) => ReactNode;
  mobileTrailing: (ctx: TrackRowContext<unknown>) => ReactNode;
  // Original item + track for render prop ctx
  item: unknown;
  track: Track;
  // Callbacks
  onMobileClick: () => void;
  onDesktopClick: (e: React.MouseEvent) => void;
  onDoubleClick: () => void;
  onPlayClick: (e: React.MouseEvent) => void;
  onContextMenu: (e: React.MouseEvent) => void;
  onDragStart?: (e: React.DragEvent) => void;
  onDragOver?: (e: React.DragEvent) => void;
  onDragLeave?: () => void;
  onDrop?: () => void;
  onDragEnd?: () => void;
  // Virtualizer
  measureElement: (el: HTMLElement | null) => void;
}

export const PlaylistRow = memo(function PlaylistRow(props: PlaylistRowProps) {
  const {
    id, virtualStart, virtualIndex, index,
    isCurrentTrack, isPlaying, isSelected,
    gridColumns, visibleColumnIds,
    isDragged, isDropTarget, draggable, extraRowClass,
    renderTitleBadge, renderDragHandle, desktopTrailing, mobileTrailing,
    item, track,
    onMobileClick, onDesktopClick, onDoubleClick, onPlayClick, onContextMenu,
    onDragStart, onDragOver, onDragLeave, onDrop, onDragEnd,
    measureElement,
  } = props;

  const isLoadingAudio = usePlayerStore((s) => s.isLoadingAudio);
  const loadingClass = isCurrentTrack && isLoadingAudio ? 'animate-pulse bg-green-500/5' : '';
  const selectedClass = isSelected ? 'bg-green-900/30 ring-1 ring-green-500/50' : '';
  const currentClass = isCurrentTrack ? 'bg-zinc-800/30' : '';
  const dragClass = `${isDragged ? 'opacity-50' : ''} ${isDropTarget ? 'border-t-2 border-green-500' : ''}`;

  // Build context for render props
  const ctx = {
    item, track, index, isCurrentTrack, isPlaying, isSelected,
  } as TrackRowContext<unknown>;

  return (
    <div
      key={id}
      data-index={virtualIndex}
      ref={measureElement}
      data-list-index={index}
      style={{
        position: 'absolute',
        top: 0,
        left: 0,
        width: '100%',
        transform: `translateY(${virtualStart}px)`,
      }}
    >
      {/* Mobile layout */}
      <div
        data-testid="playlist-track-row-mobile"
        onClick={onMobileClick}
        onDoubleClick={onDoubleClick}
        onContextMenu={track.id ? onContextMenu : undefined}
        className={`sm:hidden flex items-center gap-3 px-4 py-3 rounded-lg hover:bg-zinc-800/50 cursor-pointer transition-colors ${currentClass} ${selectedClass} ${loadingClass} ${extraRowClass}`}
      >
        <div className="w-8 flex-shrink-0 text-center cursor-pointer active:scale-90 active:opacity-70 transition-transform duration-75" onClick={onPlayClick} onTouchStart={() => {/* iOS :active CSS */}}>
          <PlayIndicator isCurrent={isCurrentTrack} isPlaying={isPlaying} index={index + 1} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className={`font-medium truncate ${isCurrentTrack ? 'text-green-500' : ''}`}>
              {track.title || 'Unknown Title'}
            </span>
            {renderTitleBadge?.(ctx)}
          </div>
          <div className="text-sm text-zinc-400 truncate">
            {track.artist || 'Unknown Artist'}
            {track.album && <span className="text-zinc-500"> &bull; {track.album}</span>}
          </div>
        </div>
        {mobileTrailing(ctx)}
      </div>

      {/* Desktop layout */}
      <div
        data-testid="playlist-track-row-desktop"
        draggable={draggable}
        onDragStart={onDragStart}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        onDragEnd={onDragEnd}
        onClick={onDesktopClick}
        onDoubleClick={onDoubleClick}
        onContextMenu={track.id ? onContextMenu : undefined}
        className={`hidden sm:grid group gap-4 px-4 py-2 items-center rounded-lg hover:bg-zinc-800/50 cursor-pointer transition-all ${currentClass} ${selectedClass} ${loadingClass} ${dragClass} ${extraRowClass}`}
        style={{ gridTemplateColumns: gridColumns }}
      >
        {/* Index cell */}
        <div className="flex items-center">
          {renderDragHandle?.(ctx)}
          <div className="flex-1 text-center cursor-pointer active:scale-90 active:opacity-70 transition-transform duration-75" onClick={onPlayClick} onTouchStart={() => {/* iOS :active CSS */}}>
            <PlayIndicator isCurrent={isCurrentTrack} isPlaying={isPlaying} index={index + 1} />
          </div>
        </div>

        {/* Title + artist */}
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className={`font-medium truncate ${isCurrentTrack ? 'text-green-500' : ''}`}>
              {track.title || 'Unknown Title'}
            </span>
            {renderTitleBadge?.(ctx)}
          </div>
          <div className="text-sm text-zinc-400 truncate sm:hidden">
            {track.artist || 'Unknown Artist'}
            {track.album && <span className="text-zinc-500"> &bull; {track.album}</span>}
          </div>
        </div>

        {/* Dynamic columns */}
        {visibleColumnIds.map((colId) => {
          const colDef = getColumnDef(colId);
          if (!colDef) return <div key={colId} />;
          const raw = colDef.getValue(track);
          const display = colDef.format ? colDef.format(raw) : (raw ?? '-');
          return (
            <div
              key={colId}
              className={`hidden sm:block text-sm text-zinc-400 truncate ${
                colDef.align === 'right' ? 'text-right' : colDef.align === 'center' ? 'text-center' : ''
              }`}
            >
              {String(display)}
            </div>
          );
        })}

        {/* Trailing cells */}
        {desktopTrailing(ctx)}
      </div>
    </div>
  );
}, (prev, next) => {
  // Custom comparator: only re-render when visible state changes
  return (
    prev.id === next.id &&
    prev.virtualStart === next.virtualStart &&
    prev.isCurrentTrack === next.isCurrentTrack &&
    prev.isPlaying === next.isPlaying &&
    prev.isSelected === next.isSelected &&
    prev.isDragged === next.isDragged &&
    prev.isDropTarget === next.isDropTarget &&
    prev.gridColumns === next.gridColumns &&
    prev.extraRowClass === next.extraRowClass &&
    prev.trackTitle === next.trackTitle &&
    prev.trackArtist === next.trackArtist &&
    prev.trackAlbum === next.trackAlbum &&
    prev.trackDurationSeconds === next.trackDurationSeconds
  );
});
