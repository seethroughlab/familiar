/**
 * Shared track list component for all playlist detail views.
 *
 * Handles: column setup, sorting, multi-select (click/shift/ctrl),
 * context menu, drag-to-playlist, selection toolbar, play indicator, empty state.
 *
 * Customized via render props for per-view trailing cells, badges, bulk actions, etc.
 */
import { useMemo, useCallback, useRef, useEffect, type ReactNode } from 'react';
import { Music, X } from 'lucide-react';
import { usePlayerStore } from '../../stores/playerStore';
import { PlayIndicator } from '../common/PlayIndicator';
import { useColumnStore, getVisibleColumns } from '../../stores/columnStore';
import { getColumnDef } from '../Library/columnDefinitions';
import { useLocalSort, useSortedTracks, buildGridColumns } from './PlaylistColumns';
import { PlaylistColumnHeader } from './PlaylistColumnHeader';
import { useClientAlphabetBar } from './useClientAlphabetBar';
import { AlphabetBar } from '../Library/AlphabetBar';
import { useMultiSelect } from '../../hooks/useMultiSelect';
import { useTrackContextMenu } from '../../hooks/useTrackContextMenu';
import { formatDuration } from '../../utils/format';
import { FavoriteButton } from '../Library/browsers/trackList/FavoriteButton';
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

export interface PlaylistTrackListProps<T> {
  /** The raw items to display (before sorting). */
  items: T[];
  /** Convert an item to a Track (for sorting, context menu, etc.). Return null for unsortable items. */
  getTrack: (item: T) => Track | null;
  /** Unique ID for each item (defaults to getTrack(item)?.id). */
  getItemId?: (item: T) => string;
  /** Called when user double-clicks or clicks the play indicator to play from an index. */
  onPlay: (index: number, sortedItems: T[]) => void;

  // --- Column customization ---
  /** Grid widths for trailing columns (default: ['3rem', '4.5rem'] for heart + duration). */
  trailingColumns?: string[];

  // --- Render props for per-view customization ---
  /** Render trailing cells for the desktop grid row. Default: FavoriteButton + Duration. */
  renderDesktopTrailing?: (ctx: TrackRowContext<T>) => ReactNode;
  /** Render trailing cells for the mobile row. Default: FavoriteButton + Duration. */
  renderMobileTrailing?: (ctx: TrackRowContext<T>) => ReactNode;
  /** Render an inline badge next to the title (e.g. "Not in library"). */
  renderTitleBadge?: (ctx: TrackRowContext<T>) => ReactNode;
  /** Extra CSS class for a row (e.g. opacity for external tracks). */
  getRowClassName?: (ctx: TrackRowContext<T>) => string;
  /** Render view-specific bulk action buttons in the selection toolbar. */
  renderBulkActions?: (selectedIds: Set<string>, clearSelection: () => void) => ReactNode;

  // --- Drag reorder (only PlaylistDetail) ---
  dragReorder?: {
    onDragStart: (item: T, e: React.DragEvent) => void;
    onDragOver: (item: T, e: React.DragEvent) => void;
    onDragLeave: () => void;
    onDrop: (item: T) => void;
    onDragEnd: () => void;
    isDragged: (item: T) => boolean;
    isDropTarget: (item: T) => boolean;
    /** Whether drag reorder is disabled (e.g. offline). */
    disabled?: boolean;
  };

  /** Render a drag handle in the index cell (for PlaylistDetail's GripVertical). */
  renderDragHandle?: (ctx: TrackRowContext<T>) => ReactNode;

  /** Empty state message. */
  emptyMessage?: string;
  /** Secondary empty state message. */
  emptySubMessage?: string;

  /** Queue source context for the player. */
  queueSource?: { type: string; id: string };

  /** Additional context menu options. */
  contextMenuOptions?: {
    onRemoveFromDownloads?: (track: Track) => void;
    onRemoveFromPlaylist?: (track: Track) => void;
  };

  /** Persist sort preferences to localStorage under this key. */
  sortPersistKey?: string;

  /** Default sort field when user hasn't explicitly chosen one (e.g. 'artist'). */
  defaultSortBy?: string;
}

export function PlaylistTrackList<T>({
  items,
  getTrack,
  getItemId,
  onPlay,
  trailingColumns = ['3rem', '4.5rem'],
  renderDesktopTrailing,
  renderMobileTrailing,
  renderTitleBadge,
  getRowClassName,
  renderBulkActions,
  dragReorder,
  renderDragHandle,
  emptyMessage = 'No tracks',
  emptySubMessage,
  contextMenuOptions,
  sortPersistKey,
  defaultSortBy,
}: PlaylistTrackListProps<T>) {
  // Player state
  const currentTrack = usePlayerStore((s) => s.currentTrack);
  const isPlaying = usePlayerStore((s) => s.isPlaying);

  // Auto-scroll to currently playing track
  const currentTrackRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (currentTrackRef.current) {
      currentTrackRef.current.scrollIntoView({ block: 'center', behavior: 'instant' });
    }
  }, [currentTrack?.id]);

  // Column + sort state
  const columns = useColumnStore((s) => s.columns);
  const { sortBy, sortOrder, toggleSort } = useLocalSort(sortPersistKey, defaultSortBy ?? null);
  const visibleColumnIds = useMemo(() => getVisibleColumns(columns), [columns]);
  const gridColumns = useMemo(
    () => buildGridColumns(columns, trailingColumns),
    [columns, trailingColumns],
  );

  // Sort items
  const sortedItems = useSortedTracks(items, sortBy, sortOrder, getTrack);

  // Alphabet bar (client-side, no backend call needed)
  const { letterIndex, activeLetter, isVisible: alphabetBarVisible, jumpToLetter } =
    useClientAlphabetBar({ sortedItems, getTrack, sortBy });

  // Multi-select
  const {
    selectedIds,
    handleItemClick: handleMultiSelectClick,
    clearSelection,
    isSelected,
    toggleItem,
  } = useMultiSelect();

  // Build ordered IDs for shift-range selection
  const orderedIds = useMemo(
    () => sortedItems.map(item => {
      if (getItemId) return getItemId(item);
      return getTrack(item)?.id ?? '';
    }),
    [sortedItems, getTrack, getItemId],
  );

  // Context menu
  const { handleContextMenu, contextMenuElement } = useTrackContextMenu({
    onPlay: (track) => {
      const idx = sortedItems.findIndex(item => {
        const id = getItemId ? getItemId(item) : getTrack(item)?.id;
        return id === track.id;
      });
      if (idx !== -1) onPlay(idx, sortedItems);
    },
    selectedTrackIds: selectedIds,
    onToggleSelect: (track) => toggleItem(track.id),
    onClearSelection: clearSelection,
    onRemoveFromDownloads: contextMenuOptions?.onRemoveFromDownloads,
    onRemoveFromPlaylist: contextMenuOptions?.onRemoveFromPlaylist,
    resolveSelectedTracks: (ids) => sortedItems
      .filter(item => {
        const itemId = getItemId ? getItemId(item) : getTrack(item)?.id ?? '';
        return ids.has(itemId);
      })
      .map(item => getTrack(item))
      .filter((t): t is Track => t !== null),
  });

  // Row click handler: single click = select, double click = play
  const handleRowClick = useCallback((item: T, index: number, e: React.MouseEvent) => {
    const id = getItemId ? getItemId(item) : getTrack(item)?.id ?? '';
    if (e.shiftKey || e.metaKey || e.ctrlKey) {
      // Modifier click: always select
      handleMultiSelectClick(id, index, e, orderedIds);
    } else {
      // Plain click: select (single)
      handleMultiSelectClick(id, index, e, orderedIds);
    }
  }, [getItemId, getTrack, handleMultiSelectClick, orderedIds]);

  const handleRowDoubleClick = useCallback((_item: T, index: number) => {
    clearSelection();
    onPlay(index, sortedItems);
  }, [onPlay, clearSelection, sortedItems]);

  // Play indicator click handler (always plays)
  const handlePlayClick = useCallback((index: number, e: React.MouseEvent) => {
    e.stopPropagation();
    clearSelection();
    onPlay(index, sortedItems);
  }, [onPlay, clearSelection, sortedItems]);

  // Build row context
  const buildCtx = useCallback((item: T, index: number): TrackRowContext<T> => {
    const track = getTrack(item);
    const id = getItemId ? getItemId(item) : track?.id ?? '';
    return {
      item,
      track: track ?? { id, file_path: '', title: null, artist: null, album: null, album_artist: null, album_type: 'album', track_number: null, disc_number: null, year: null, genre: null, duration_seconds: null, format: null, analysis_version: 0 },
      index,
      isCurrentTrack: currentTrack?.id === (track?.id ?? id),
      isPlaying,
      isSelected: isSelected(id),
    };
  }, [getTrack, getItemId, currentTrack?.id, isPlaying, isSelected]);

  // Default trailing renderers
  const defaultDesktopTrailing = useCallback((ctx: TrackRowContext<T>) => (
    <>
      <FavoriteButton trackId={ctx.track.id} />
      <div className="text-sm text-zinc-500 text-right">
        {formatDuration(ctx.track.duration_seconds)}
      </div>
    </>
  ), []);

  const defaultMobileTrailing = useCallback((ctx: TrackRowContext<T>) => (
    <>
      <FavoriteButton trackId={ctx.track.id} />
      <div className="flex-shrink-0 text-sm text-zinc-500">
        {formatDuration(ctx.track.duration_seconds)}
      </div>
    </>
  ), []);

  const desktopTrailing = renderDesktopTrailing ?? defaultDesktopTrailing;
  const mobileTrailing = renderMobileTrailing ?? defaultMobileTrailing;

  if (sortedItems.length === 0) {
    return (
      <div className="text-center py-12 text-zinc-500">
        <Music className="w-12 h-12 mx-auto mb-3 opacity-50" />
        <p>{emptyMessage}</p>
        {emptySubMessage && <p className="text-sm mt-1">{emptySubMessage}</p>}
      </div>
    );
  }

  return (
    <div>
      {/* Selection toolbar */}
      {selectedIds.size > 0 && (
        <div className="sticky top-0 z-10 bg-zinc-900/95 backdrop-blur-sm p-3 rounded-lg flex items-center gap-3 border border-zinc-700 mb-2">
          <span className="text-sm text-zinc-300 font-medium">
            {selectedIds.size} track{selectedIds.size !== 1 ? 's' : ''} selected
          </span>
          <div className="flex-1" />
          {renderBulkActions?.(selectedIds, clearSelection)}
          <button
            onClick={clearSelection}
            className="p-1.5 hover:bg-zinc-700 rounded-md transition-colors"
            title="Clear selection"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Column header */}
      <PlaylistColumnHeader
        columns={columns}
        gridColumns={gridColumns}
        sortBy={sortBy}
        sortOrder={sortOrder}
        toggleSort={toggleSort}
        trailingCount={trailingColumns.length}
      />

      {/* Track rows */}
      <div className="space-y-1">
        {sortedItems.map((item, idx) => {
          const ctx = buildCtx(item, idx);
          const id = getItemId ? getItemId(item) : ctx.track.id;
          const extraRowClass = getRowClassName?.(ctx) ?? '';
          const selectedClass = ctx.isSelected ? 'bg-green-900/30 ring-1 ring-green-500/50' : '';
          const currentClass = ctx.isCurrentTrack ? 'bg-zinc-800/30' : '';

          // Drag reorder classes
          const dragClass = dragReorder
            ? `${dragReorder.isDragged(item) ? 'opacity-50' : ''} ${dragReorder.isDropTarget(item) ? 'border-t-2 border-green-500' : ''}`
            : '';

          return (
            <div key={id} data-list-index={idx} ref={ctx.isCurrentTrack ? currentTrackRef : undefined}>
              {/* Mobile layout */}
              <div
                onClick={(e) => handleRowClick(item, idx, e)}
                onDoubleClick={() => handleRowDoubleClick(item, idx)}
                onContextMenu={(e) => ctx.track.id && handleContextMenu(ctx.track, e)}
                className={`sm:hidden flex items-center gap-3 px-4 py-3 rounded-lg hover:bg-zinc-800/50 cursor-pointer transition-colors ${currentClass} ${selectedClass} ${extraRowClass}`}
              >
                <div className="w-8 flex-shrink-0 text-center" onClick={(e) => handlePlayClick(idx, e)}>
                  <PlayIndicator isCurrent={ctx.isCurrentTrack} isPlaying={ctx.isPlaying} index={idx + 1} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={`font-medium truncate ${ctx.isCurrentTrack ? 'text-green-500' : ''}`}>
                      {ctx.track.title || 'Unknown Title'}
                    </span>
                    {renderTitleBadge?.(ctx)}
                  </div>
                  <div className="text-sm text-zinc-400 truncate">
                    {ctx.track.artist || 'Unknown Artist'}
                    {ctx.track.album && <span className="text-zinc-500"> &bull; {ctx.track.album}</span>}
                  </div>
                </div>
                {mobileTrailing(ctx)}
              </div>

              {/* Desktop layout */}
              <div
                draggable={dragReorder ? !dragReorder.disabled : true}
                onDragStart={(e) => {
                  if (dragReorder && !dragReorder.disabled) {
                    dragReorder.onDragStart(item, e);
                  } else {
                    e.dataTransfer.setData('application/track-id', ctx.track.id);
                    e.dataTransfer.effectAllowed = 'copy';
                  }
                }}
                onDragOver={dragReorder && !dragReorder.disabled ? (e) => dragReorder.onDragOver(item, e) : undefined}
                onDragLeave={dragReorder ? dragReorder.onDragLeave : undefined}
                onDrop={dragReorder && !dragReorder.disabled ? () => dragReorder.onDrop(item) : undefined}
                onDragEnd={dragReorder ? dragReorder.onDragEnd : undefined}
                onClick={(e) => handleRowClick(item, idx, e)}
                onDoubleClick={() => handleRowDoubleClick(item, idx)}
                onContextMenu={(e) => ctx.track.id && handleContextMenu(ctx.track, e)}
                className={`hidden sm:grid group gap-4 px-4 py-2 items-center rounded-lg hover:bg-zinc-800/50 cursor-pointer transition-all ${currentClass} ${selectedClass} ${dragClass} ${extraRowClass}`}
                style={{ gridTemplateColumns: gridColumns }}
              >
                {/* Index cell */}
                <div className="flex items-center">
                  {renderDragHandle?.(ctx)}
                  <div className="flex-1 text-center cursor-pointer" onClick={(e) => handlePlayClick(idx, e)}>
                    <PlayIndicator isCurrent={ctx.isCurrentTrack} isPlaying={ctx.isPlaying} index={idx + 1} />
                  </div>
                </div>

                {/* Title + artist */}
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={`font-medium truncate ${ctx.isCurrentTrack ? 'text-green-500' : ''}`}>
                      {ctx.track.title || 'Unknown Title'}
                    </span>
                    {renderTitleBadge?.(ctx)}
                  </div>
                  <div className="text-sm text-zinc-400 truncate sm:hidden">
                    {ctx.track.artist || 'Unknown Artist'}
                    {ctx.track.album && <span className="text-zinc-500"> &bull; {ctx.track.album}</span>}
                  </div>
                </div>

                {/* Dynamic columns */}
                {visibleColumnIds.map((colId) => {
                  const colDef = getColumnDef(colId);
                  if (!colDef) return <div key={colId} />;
                  const raw = colDef.getValue(ctx.track);
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
        })}
      </div>

      {/* Context menu */}
      {contextMenuElement}

      {/* Alphabet bar (A-Z quick navigation for large sorted lists) */}
      <AlphabetBar
        letterIndex={letterIndex}
        activeLetter={activeLetter}
        onLetterSelect={jumpToLetter}
        visible={alphabetBarVisible}
      />
    </div>
  );
}
