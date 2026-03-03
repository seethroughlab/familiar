import { useState, useCallback, useRef, useEffect } from 'react';
import { ListMusic, ListX, GripVertical, X, Shuffle, Trash2, Music, Plus } from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';
import { usePlayerStore } from '../../stores/playerStore';
import { PlayIndicator } from '../common/PlayIndicator';
import { useThemeStore } from '../../stores/themeStore';
import { useSelectionStore } from '../../stores/selectionStore';
import { useAppNavigation } from '../../hooks/useAppNavigation';
import { useFavorites } from '../../hooks/useFavorites';
import { tracksApi } from '../../api';
import { TrackContextMenu } from '../Library/TrackContextMenu';
import type { ContextMenuState } from '../Library/types';
import { initialContextMenuState } from '../Library/types';
import type { Track } from '../../types';
import { useUIStore } from '../../stores/uiStore';

import { createLogger } from '../../utils/logger';

const log = createLogger('QueueView');

interface QueueViewProps {
  onTrackDropped?: (trackId: string) => void;
}

export function QueueView({ onTrackDropped }: QueueViewProps = {}) {
  const { queue, queueIndex, isPlaying, shuffle, consume, lazyQueueIds, shuffleOrder } = usePlayerStore(
    useShallow((s) => ({
      queue: s.queue, queueIndex: s.queueIndex,
      isPlaying: s.isPlaying, shuffle: s.shuffle, consume: s.consume,
      lazyQueueIds: s.lazyQueueIds,
      shuffleOrder: s.shuffleOrder,
    }))
  );
  const clearQueue = usePlayerStore((s) => s.clearQueue);
  const removeFromQueue = usePlayerStore((s) => s.removeFromQueue);
  const exitLazyMode = usePlayerStore((s) => s.exitLazyMode);
  const addToQueue = usePlayerStore((s) => s.addToQueue);
  const toggleConsume = usePlayerStore((s) => s.toggleConsume);

  const resolvedTheme = useThemeStore((state) => state.resolvedTheme);
  const { navigateToArtist, navigateToAlbum } = useAppNavigation();
  const { isFavorite, toggle: toggleFavorite } = useFavorites();
  const [contextMenu, setContextMenu] = useState<ContextMenuState>(initialContextMenuState);

  // Ref for auto-scrolling to the current track
  const currentTrackRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (currentTrackRef.current) {
      currentTrackRef.current.scrollIntoView({ block: 'center', behavior: 'instant' });
    }
  }, [queueIndex]);

  // Pointer-event drag-to-reorder state (works on both mouse and touch)
  const [draggedIndex, setDraggedIndex] = useState<number | null>(null);
  const [dropTargetIndex, setDropTargetIndex] = useState<number | null>(null);
  const [pointerDeltaY, setPointerDeltaY] = useState(0);
  const dragStartY = useRef(0);
  const itemRectsRef = useRef<DOMRect[]>([]);
  const rowRefsRef = useRef<(HTMLDivElement | null)[]>([]);

  // Flag to suppress the synthetic click that fires after a pointer-event drag reorder
  const didDragRef = useRef(false);

  // External HTML5 DnD state (library → queue drops only)
  const [externalDropTargetIndex, setExternalDropTargetIndex] = useState<number | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);

  const isLazyMode = lazyQueueIds && lazyQueueIds.length > 0;

  // Get reorder and jump actions from store
  const reorderQueue = usePlayerStore((state) => state.reorderQueue);
  const reorderShuffleOrder = usePlayerStore((state) => state.reorderShuffleOrder);
  const jumpToQueueIndex = usePlayerStore((state) => state.jumpToQueueIndex);

  // Pointer-event drag handlers for reorder (works on touch + mouse)
  const handlePointerDown = useCallback((index: number, e: React.PointerEvent) => {
    e.preventDefault();
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    dragStartY.current = e.clientY;
    setDraggedIndex(index);
    setPointerDeltaY(0);
    // Snapshot all row bounding rects for hit-testing
    itemRectsRef.current = rowRefsRef.current.map(el => el?.getBoundingClientRect() ?? new DOMRect());
  }, []);

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    if (draggedIndex === null) return;
    const deltaY = e.clientY - dragStartY.current;
    setPointerDeltaY(deltaY);

    // Hit-test: which row's vertical midpoint has the pointer crossed?
    const rects = itemRectsRef.current;
    for (let i = 0; i < rects.length; i++) {
      const mid = rects[i].top + rects[i].height / 2;
      if (e.clientY < mid) {
        setDropTargetIndex(i !== draggedIndex ? i : null);
        return;
      }
    }
    // Past the last item
    const lastIdx = rects.length - 1;
    if (lastIdx >= 0 && lastIdx !== draggedIndex) {
      setDropTargetIndex(lastIdx);
    }
  }, [draggedIndex]);

  const handlePointerUp = useCallback((e: React.PointerEvent) => {
    (e.target as HTMLElement).releasePointerCapture(e.pointerId);
    if (draggedIndex !== null && dropTargetIndex !== null && draggedIndex !== dropTargetIndex) {
      if (shuffle && shuffleOrder.length > 0) {
        reorderShuffleOrder(draggedIndex, dropTargetIndex);
      } else {
        reorderQueue(draggedIndex, dropTargetIndex);
      }
      didDragRef.current = true;
    }
    setDraggedIndex(null);
    setDropTargetIndex(null);
    setPointerDeltaY(0);
  }, [draggedIndex, dropTargetIndex, shuffle, shuffleOrder, reorderQueue, reorderShuffleOrder]);

  const handlePointerCancel = useCallback((e: React.PointerEvent) => {
    (e.target as HTMLElement).releasePointerCapture(e.pointerId);
    setDraggedIndex(null);
    setDropTargetIndex(null);
    setPointerDeltaY(0);
  }, []);

  // Per-row handlers for external HTML5 DnD drops (library → queue)
  const handleRowDragOver = useCallback((e: React.DragEvent, targetIndex: number) => {
    if (e.dataTransfer.types.includes('application/track-id')) {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'copy';
      setExternalDropTargetIndex(targetIndex);
    }
  }, []);

  const handleRowDragLeave = useCallback(() => {
    setExternalDropTargetIndex(null);
  }, []);

  // Handle external track drop at a specific queue position
  const handleExternalDropAtPosition = useCallback(async (e: React.DragEvent, displayIndex: number) => {
    e.preventDefault();
    setExternalDropTargetIndex(null);
    setIsDragOver(false);

    const trackId = e.dataTransfer.getData('application/track-id');
    if (!trackId) return;

    try {
      const tracks = await tracksApi.getBatch([trackId]);
      if (tracks.length > 0) {
        if (shuffle && shuffleOrder.length > 0) {
          // In shuffle mode: append to queue end, insert into shuffleOrder at display position
          addToQueue(tracks[0], undefined, displayIndex + 1);
        } else {
          // Normal mode: insert after the hovered item
          addToQueue(tracks[0], displayIndex + 1);
        }
        onTrackDropped?.(trackId);
      }
    } catch (error) {
      log.error('Failed to add track to queue:', error);
    }
  }, [addToQueue, onTrackDropped, shuffle, shuffleOrder]);

  // Handle external track drops (from library) — fallback for empty space
  const handleExternalDragOver = useCallback((e: React.DragEvent) => {
    // Check if this is an external track drop (not internal reorder)
    if (e.dataTransfer.types.includes('application/track-id')) {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'copy';
      setIsDragOver(true);
    }
  }, []);

  const handleExternalDragLeave = useCallback(() => {
    setIsDragOver(false);
  }, []);

  const handleExternalDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);

    const trackId = e.dataTransfer.getData('application/track-id');
    if (trackId) {
      // Fetch track and add to queue
      try {
        const tracks = await tracksApi.getBatch([trackId]);
        if (tracks.length > 0) {
          addToQueue(tracks[0]);
          onTrackDropped?.(trackId);
        }
      } catch (error) {
        log.error('Failed to add track to queue:', error);
      }
    }
  }, [addToQueue, onTrackDropped]);

  // Handle clicking on a track to jump to it
  const handleTrackClick = useCallback((index: number) => {
    if (didDragRef.current) {
      didDragRef.current = false;
      return;
    }
    jumpToQueueIndex(index);
  }, [jumpToQueueIndex]);

  // Handle removing a track from queue
  const handleRemoveTrack = useCallback((queueId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    removeFromQueue(queueId);
  }, [removeFromQueue]);

  // Handle clearing the entire queue
  const handleClearAll = useCallback(() => {
    if (isLazyMode) {
      exitLazyMode();
    }
    clearQueue();
  }, [isLazyMode, exitLazyMode, clearQueue]);

  // Context menu handlers
  const handleContextMenu = useCallback((track: Track, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setContextMenu({ isOpen: true, track, position: { x: e.clientX, y: e.clientY } });
  }, []);

  const closeContextMenu = useCallback(() => {
    setContextMenu(initialContextMenuState);
  }, []);

  const formatDuration = (seconds: number | null) => {
    if (!seconds) return '--:--';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  // Build display tracks — respect shuffle order when active
  const totalCount = isLazyMode ? lazyQueueIds.length : queue.length;
  const displayTracks = (shuffle && shuffleOrder.length > 0)
    ? shuffleOrder
        .map((queueIdx) => ({
          track: queue[queueIdx]?.track,
          queueId: queue[queueIdx]?.queueId,
          isCurrent: queueIdx === queueIndex,
          actualQueueIndex: queueIdx,
        }))
        .filter(item => item.track != null)
    : queue.map((item, index) => ({
        track: item.track,
        queueId: item.queueId,
        isCurrent: index === queueIndex,
        actualQueueIndex: index,
      }));

  const isEmpty = totalCount === 0;

  return (
    <div
      className={`h-full flex flex-col ${isDragOver ? 'ring-2 ring-green-500 ring-inset' : ''}`}
      onDragOver={handleExternalDragOver}
      onDragLeave={handleExternalDragLeave}
      onDrop={handleExternalDrop}
    >
      {/* Header */}
      <div className={`px-4 py-4 border-b ${resolvedTheme === 'light' ? 'border-zinc-200' : 'border-zinc-800'}`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <ListMusic className="w-6 h-6 text-green-500" />
            <div>
              <h1 className="text-xl font-bold">Queue</h1>
              <p className="text-sm text-zinc-500">
                {totalCount} track{totalCount !== 1 ? 's' : ''}
                {shuffle && (
                  <span className="ml-2 inline-flex items-center gap-1 text-green-500">
                    <Shuffle className="w-3 h-3" />
                    Shuffle
                  </span>
                )}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={toggleConsume}
              className={`p-2 rounded-lg transition-colors ${
                consume
                  ? 'text-green-500'
                  : resolvedTheme === 'light'
                    ? 'text-zinc-400 hover:text-zinc-700'
                    : 'text-zinc-400 hover:text-zinc-200'
              }`}
              aria-label={consume ? 'Disable consume mode' : 'Enable consume mode'}
              aria-pressed={consume}
              title="Consume: remove tracks after playing"
            >
              <ListX className="w-5 h-5" />
            </button>
            {!isEmpty && (
              <button
                onClick={handleClearAll}
                className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm transition-colors ${
                  resolvedTheme === 'light'
                    ? 'bg-zinc-100 hover:bg-zinc-200 text-zinc-700'
                    : 'bg-zinc-800 hover:bg-zinc-700 text-zinc-300'
                }`}
              >
                <Trash2 className="w-4 h-4" />
                Clear All
              </button>
            )}
          </div>
        </div>

        {/* Library playback info banner */}
        {isLazyMode && (
          <div className={`mt-3 px-3 py-2 rounded-lg text-sm ${
            resolvedTheme === 'light'
              ? 'bg-green-50 text-green-700 border border-green-200'
              : 'bg-green-900/20 text-green-400 border border-green-800'
          }`}>
            <div className="flex items-center gap-2">
              <Shuffle className="w-4 h-4" />
              <span>Playing from library ({totalCount.toLocaleString()} tracks) — showing next {queue.length}</span>
            </div>
          </div>
        )}
      </div>

      {/* Track list */}
      <div className="flex-1 overflow-y-auto">
        {isEmpty ? (
          <div className={`flex flex-col items-center justify-center h-full text-center px-4 ${
            isDragOver ? 'bg-green-900/10' : ''
          }`}>
            {isDragOver ? (
              <>
                <Plus className="w-16 h-16 text-green-500 mb-4" />
                <h2 className="text-lg font-medium text-green-400 mb-2">Drop to add to queue</h2>
              </>
            ) : (
              <>
                <Music className="w-16 h-16 text-zinc-600 mb-4" />
                <h2 className="text-lg font-medium text-zinc-400 mb-2">Your queue is empty</h2>
                <p className="text-sm text-zinc-500 max-w-xs">
                  Drag tracks here or ask Claude to create a playlist
                </p>
              </>
            )}
          </div>
        ) : (
          <div className="py-1 space-y-1">
            {displayTracks.map((item, displayIndex) => {
              const { track, queueId, isCurrent, actualQueueIndex } = item;
              const isDragged = draggedIndex === displayIndex;
              const isReorderTarget = dropTargetIndex === displayIndex && draggedIndex !== null;
              const isExtDropTarget = externalDropTargetIndex === displayIndex;

              return (
                <div
                  key={queueId}
                  ref={(el) => {
                    rowRefsRef.current[displayIndex] = el;
                    if (isCurrent) (currentTrackRef as React.MutableRefObject<HTMLDivElement | null>).current = el;
                  }}
                  onDragOver={(e) => handleRowDragOver(e, displayIndex)}
                  onDragLeave={handleRowDragLeave}
                  onDrop={(e) => {
                    if (e.dataTransfer.types.includes('application/track-id')) {
                      e.stopPropagation();
                      handleExternalDropAtPosition(e, displayIndex);
                    }
                  }}
                  onClick={() => handleTrackClick(actualQueueIndex)}
                  onContextMenu={(e) => handleContextMenu(track, e)}
                  style={isDragged ? { transform: `translateY(${pointerDeltaY}px)`, zIndex: 10, position: 'relative' } : undefined}
                  className={`group flex items-center gap-3 p-3 rounded-lg cursor-pointer transition-colors ${
                    isDragged ? 'shadow-lg' : ''
                  } ${
                    isCurrent
                      ? resolvedTheme === 'light'
                        ? 'bg-green-50 border border-green-200'
                        : 'bg-green-900/20 border border-green-800'
                      : resolvedTheme === 'light'
                        ? 'hover:bg-zinc-100'
                        : 'hover:bg-zinc-800/50'
                  } ${isDragged ? 'opacity-75' : ''} ${isReorderTarget || isExtDropTarget ? 'border-t-2 border-green-500' : ''}`}
                >
                  {/* Drag handle — uses pointer events for touch+mouse reorder */}
                  <div
                    className={`flex-shrink-0 cursor-grab active:cursor-grabbing transition-opacity ${
                      'opacity-50 sm:opacity-0 sm:group-hover:opacity-50 hover:!opacity-100'
                    } ${isDragged ? '!opacity-100' : ''}`}
                    style={{ touchAction: 'none' }}
                    onPointerDown={(e) => handlePointerDown(displayIndex, e)}
                    onPointerMove={handlePointerMove}
                    onPointerUp={handlePointerUp}
                    onPointerCancel={handlePointerCancel}
                  >
                    <GripVertical className="w-4 h-4 text-zinc-500" />
                  </div>

                  {/* Play indicator / number */}
                  <div className="w-8 text-center flex-shrink-0">
                    <PlayIndicator isCurrent={isCurrent} isPlaying={isPlaying} index={displayIndex + 1} />
                  </div>

                  {/* Track info */}
                  <div className="flex-1 min-w-0">
                    <div className={`font-medium truncate ${isCurrent ? 'text-green-500' : ''}`}>
                      {track.title || 'Unknown Title'}
                    </div>
                    <div className="text-sm text-zinc-500 truncate">
                      {track.artist || 'Unknown Artist'}
                      {track.album && (
                        <span className="text-zinc-600"> • {track.album}</span>
                      )}
                    </div>
                  </div>

                  {/* Duration */}
                  <div className="text-sm text-zinc-500 flex-shrink-0">
                    {formatDuration(track.duration_seconds)}
                  </div>

                  {/* Remove button */}
                  <button
                    onClick={(e) => handleRemoveTrack(queueId, e)}
                    className="p-1.5 rounded-lg opacity-0 group-hover:opacity-100 transition-opacity hover:bg-zinc-700/50"
                    title="Remove from queue"
                  >
                    <X className="w-4 h-4 text-zinc-400 hover:text-red-400" />
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Context menu */}
      {contextMenu.isOpen && contextMenu.track && (
        <TrackContextMenu
          track={contextMenu.track}
          position={contextMenu.position}
          isSelected={false}
          onClose={closeContextMenu}
          onPlay={() => {
            if (contextMenu.track) {
              const idx = queue.findIndex(q => q.track.id === contextMenu.track?.id);
              if (idx !== -1) handleTrackClick(idx);
            }
          }}
          onQueue={() => {
            if (contextMenu.track) addToQueue(contextMenu.track);
          }}
          onGoToArtist={() => {
            if (contextMenu.track?.artist) navigateToArtist(contextMenu.track.artist);
          }}
          onGoToAlbum={() => {
            if (contextMenu.track?.artist && contextMenu.track?.album) {
              navigateToAlbum(contextMenu.track.artist, contextMenu.track.album);
            }
          }}
          onToggleSelect={() => {}}
          onAddToPlaylist={() => {
            if (contextMenu.track) {
              useUIStore.getState().openPlaylistPicker([contextMenu.track.id]);
            }
          }}
          onMakePlaylist={() => {
            if (contextMenu.track) {
              const track = contextMenu.track;
              const message = `Make me a playlist based on "${track.title || 'this track'}" by ${track.artist || 'Unknown Artist'}`;
              useUIStore.getState().triggerChat(message);
            }
          }}
          onEditMetadata={() => {
            if (contextMenu.track) {
              useSelectionStore.getState().setEditingTrackId(contextMenu.track.id);
            }
          }}
          isFavorite={contextMenu.track ? isFavorite(contextMenu.track.id) : false}
          onToggleFavorite={() => {
            if (contextMenu.track) toggleFavorite(contextMenu.track.id);
          }}
        />
      )}
    </div>
  );
}
