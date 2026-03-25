/**
 * Shared track list component for all playlist detail views.
 *
 * Handles: column setup, sorting, multi-select (click/shift/ctrl),
 * context menu, drag-to-playlist, selection toolbar, play indicator, empty state.
 *
 * Customized via render props for per-view trailing cells, badges, bulk actions, etc.
 */
import { useMemo, useCallback, useRef, useEffect, useLayoutEffect, useState, type ReactNode } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { Music, X } from 'lucide-react';
import { usePlayerStore } from '../../stores/playerStore';
import { useColumnStore, getVisibleColumns } from '../../stores/columnStore';
import { useLocalSort, useSortedTracks, buildGridColumns } from './PlaylistColumns';
import { PlaylistColumnHeader } from './PlaylistColumnHeader';
import { useClientAlphabetBar } from './useClientAlphabetBar';
import { AlphabetBar } from '../Library/AlphabetBar';
import { useMultiSelect } from '../../hooks/useMultiSelect';
import { useTrackContextMenu } from '../../hooks/useTrackContextMenu';
import { useOfflineStatus } from '../../hooks/useOfflineStatus';
import { useOfflineTrackIds } from '../../hooks/useOfflineTrack';
import { useScrollContainer } from '../../hooks/useScrollContainer';
import { formatDuration } from '../../utils/format';
import { FavoriteButton } from '../Library/browsers/trackList/FavoriteButton';
import type { Track } from '../../types';
import { resolveTrackRowIntent } from './trackRowInteraction';
import { PlaylistRow, type TrackRowContext } from './PlaylistRow';
export type { TrackRowContext } from './PlaylistRow';

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
  const { isOffline } = useOfflineStatus();
  const { offlineIds } = useOfflineTrackIds();

  const visibleItems = useMemo(() => {
    if (!isOffline) return items;
    return items.filter((item) => {
      const track = getTrack(item);
      return !!track && offlineIds.has(track.id);
    });
  }, [isOffline, items, getTrack, offlineIds]);

  // Player state
  const currentTrack = usePlayerStore((s) => s.currentTrack);
  const isPlaying = usePlayerStore((s) => s.isPlaying);

  // Scroll container for virtualization — prefer AppShell's shared scroll
  // container so the header above the track list scrolls away on mobile.
  const parentScrollRef = useScrollContainer();
  const useParentScroll = !!parentScrollRef;
  const scrollRef = useRef<HTMLDivElement>(null);
  const virtualContainerRef = useRef<HTMLDivElement>(null);

  // Measure offset of virtual items from scroll container for scrollMargin.
  // Re-measured when items change (header may show/hide loading states).
  const [scrollMargin, setScrollMargin] = useState(0);
  useLayoutEffect(() => {
    if (!useParentScroll) return;
    const scrollEl = parentScrollRef?.current;
    const listEl = virtualContainerRef.current;
    if (!scrollEl || !listEl) return;
    const scrollRect = scrollEl.getBoundingClientRect();
    const listRect = listEl.getBoundingClientRect();
    setScrollMargin(listRect.top - scrollRect.top + scrollEl.scrollTop);
  }, [useParentScroll, parentScrollRef, items.length]); // eslint-disable-line react-hooks/exhaustive-deps

  // Column + sort state
  const columns = useColumnStore((s) => s.columns);
  const { sortBy, sortOrder, toggleSort, clearSort } = useLocalSort(sortPersistKey, defaultSortBy ?? null);
  const visibleColumnIds = useMemo(() => getVisibleColumns(columns), [columns]);
  const gridColumns = useMemo(
    () => buildGridColumns(columns, trailingColumns),
    [columns, trailingColumns],
  );

  // Sort items
  const sortedItems = useSortedTracks(visibleItems, sortBy, sortOrder, getTrack);

  // Virtualizer
  const virtualizer = useVirtualizer({
    count: sortedItems.length,
    getScrollElement: () => useParentScroll
      ? (parentScrollRef?.current ?? null)
      : scrollRef.current,
    estimateSize: () => 48,
    overscan: 10,
    scrollMargin: useParentScroll ? scrollMargin : 0,
  });

  // Auto-scroll to currently playing track
  useEffect(() => {
    if (!currentTrack?.id) return;
    const idx = sortedItems.findIndex((item) => {
      const track = getTrack(item);
      return track?.id === currentTrack.id;
    });
    if (idx >= 0) virtualizer.scrollToIndex(idx, { align: 'center' });
  }, [currentTrack?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Alphabet bar (client-side, no backend call needed)
  const scrollToIndex = useCallback((idx: number) => {
    virtualizer.scrollToIndex(idx, { align: 'start' });
  }, [virtualizer]);
  const { letterIndex, activeLetter, isVisible: alphabetBarVisible, jumpToLetter } =
    useClientAlphabetBar({ sortedItems, getTrack, sortBy, scrollToIndex });

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
      const idx = sortedItems.findIndex((item) => {
        const id = getItemId ? getItemId(item) : getTrack(item)?.id;
        return id === track.id;
      });
      if (idx !== -1) {
        onPlay(idx, sortedItems);
      }
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

  const playItem = useCallback((item: T) => {
    const clickedId = getItemId ? getItemId(item) : getTrack(item)?.id ?? '';
    if (!clickedId) return;

    const resolvedIndex = sortedItems.findIndex((candidate) => {
      const candidateId = getItemId ? getItemId(candidate) : getTrack(candidate)?.id ?? '';
      return candidateId === clickedId;
    });

    if (resolvedIndex === -1) return;

    clearSelection();
    onPlay(resolvedIndex, sortedItems);
  }, [clearSelection, getItemId, getTrack, onPlay, sortedItems]);

  // Row click handler: single click = select, double click = play
  const handleRowClick = useCallback((item: T, index: number, e: React.MouseEvent) => {
    const id = getItemId ? getItemId(item) : getTrack(item)?.id ?? '';
    const intent = resolveTrackRowIntent({
      isMobile: false,
      shiftKey: e.shiftKey,
      metaKey: e.metaKey,
      ctrlKey: e.ctrlKey,
    });

    if (intent === 'play') {
      playItem(item);
      return;
    }

    handleMultiSelectClick(id, index, e, orderedIds);
  }, [getItemId, getTrack, handleMultiSelectClick, orderedIds, playItem]);

  const handleMobileRowClick = useCallback((item: T) => {
    playItem(item);
  }, [playItem]);

  const handleRowDoubleClick = useCallback((item: T) => {
    playItem(item);
  }, [playItem]);

  // Play indicator click handler (always plays)
  const handlePlayClick = useCallback((item: T, e: React.MouseEvent) => {
    e.stopPropagation();
    playItem(item);
  }, [playItem]);

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
    <div className={useParentScroll ? 'flex flex-col' : 'flex flex-col min-h-0 flex-1'}>
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
        clearSort={clearSort}
        trailingCount={trailingColumns.length}
      />

      {/* Track rows (virtualized) — when using parent scroll, no inner scroll wrapper */}
      <div
        ref={useParentScroll ? virtualContainerRef : scrollRef}
        className={useParentScroll ? '' : 'flex-1 min-h-0 overflow-y-auto'}
        style={useParentScroll ? undefined : { contain: 'strict' }}
      >
        <div style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
          {virtualizer.getVirtualItems().map((virtualRow) => {
            const idx = virtualRow.index;
            const item = sortedItems[idx];
            const track = getTrack(item);
            const id = getItemId ? getItemId(item) : track?.id ?? '';
            const trackObj = track ?? { id, file_path: '', title: null, artist: null, album: null, album_artist: null, album_type: 'album' as const, track_number: null, disc_number: null, year: null, genre: null, duration_seconds: null, format: null, analysis_version: 0 };
            const isCurrent = currentTrack?.id === (track?.id ?? id);
            const selected = isSelected(id);
            const ctx = { item, track: trackObj, index: idx, isCurrentTrack: isCurrent, isPlaying, isSelected: selected } as TrackRowContext<T>;
            const extraRowClass = getRowClassName?.(ctx) ?? '';

            return (
              <PlaylistRow
                key={id}
                id={id}
                virtualStart={virtualRow.start - (useParentScroll ? scrollMargin : 0)}
                virtualIndex={virtualRow.index}
                index={idx}
                trackId={trackObj.id}
                trackTitle={trackObj.title}
                trackArtist={trackObj.artist}
                trackAlbum={trackObj.album}
                trackDurationSeconds={trackObj.duration_seconds}
                isCurrentTrack={isCurrent}
                isPlaying={isPlaying}
                isSelected={selected}
                gridColumns={gridColumns}
                visibleColumnIds={visibleColumnIds}
                isDragged={dragReorder ? dragReorder.isDragged(item) : false}
                isDropTarget={dragReorder ? dragReorder.isDropTarget(item) : false}
                draggable={dragReorder ? !dragReorder.disabled : true}
                extraRowClass={extraRowClass}
                renderTitleBadge={renderTitleBadge as ((ctx: TrackRowContext<unknown>) => ReactNode) | undefined}
                renderDragHandle={renderDragHandle as ((ctx: TrackRowContext<unknown>) => ReactNode) | undefined}
                desktopTrailing={desktopTrailing as (ctx: TrackRowContext<unknown>) => ReactNode}
                mobileTrailing={mobileTrailing as (ctx: TrackRowContext<unknown>) => ReactNode}
                item={item}
                track={trackObj}
                onMobileClick={() => handleMobileRowClick(item)}
                onDesktopClick={(e) => handleRowClick(item, idx, e)}
                onDoubleClick={() => handleRowDoubleClick(item)}
                onPlayClick={(e) => handlePlayClick(item, e)}
                onContextMenu={(e) => handleContextMenu(trackObj, e)}
                onDragStart={dragReorder && !dragReorder.disabled
                  ? (e) => dragReorder.onDragStart(item, e)
                  : (e) => { e.dataTransfer.setData('application/track-id', trackObj.id); e.dataTransfer.effectAllowed = 'copy'; }}
                onDragOver={dragReorder && !dragReorder.disabled ? (e) => dragReorder.onDragOver(item, e) : undefined}
                onDragLeave={dragReorder ? dragReorder.onDragLeave : undefined}
                onDrop={dragReorder && !dragReorder.disabled ? () => dragReorder.onDrop(item) : undefined}
                onDragEnd={dragReorder ? dragReorder.onDragEnd : undefined}
                measureElement={virtualizer.measureElement}
              />
            );
          })}
        </div>
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
