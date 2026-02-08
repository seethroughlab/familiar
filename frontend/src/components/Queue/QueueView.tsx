import { useState, useCallback, useRef, useEffect } from 'react';
import { ListMusic, Play, Pause, GripVertical, X, Shuffle, Trash2, Music, Plus } from 'lucide-react';
import { usePlayerStore } from '../../stores/playerStore';
import { useThemeStore } from '../../stores/themeStore';
import { tracksApi } from '../../api/client';
import type { Track } from '../../types';

import { createLogger } from '../../utils/logger';

const log = createLogger('QueueView');

interface QueueViewProps {
  onTrackDropped?: (trackId: string) => void;
}

export function QueueView({ onTrackDropped }: QueueViewProps = {}) {
  const {
    queue,
    queueIndex,
    currentTrack,
    isPlaying,
    shuffle,
    lazyQueueIds,
    lazyQueueIndex,
    prefetchedTracks,
    setIsPlaying,
    clearQueue,
    removeFromQueue,
    exitLazyMode,
    addToQueue,
  } = usePlayerStore();

  const resolvedTheme = useThemeStore((state) => state.resolvedTheme);

  // Ref for auto-scrolling to the current track
  const currentTrackRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (currentTrackRef.current) {
      currentTrackRef.current.scrollIntoView({ block: 'center', behavior: 'instant' });
    }
  }, [queueIndex, lazyQueueIndex]);

  // Drag-to-reorder state (only for regular queue mode)
  const [draggedIndex, setDraggedIndex] = useState<number | null>(null);
  const [dropTargetIndex, setDropTargetIndex] = useState<number | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);

  const isLazyMode = lazyQueueIds && lazyQueueIds.length > 0;

  // Get reorder and jump actions from store
  const reorderQueue = usePlayerStore((state) => state.reorderQueue);
  const jumpToQueueIndex = usePlayerStore((state) => state.jumpToQueueIndex);
  const jumpToLazyQueueIndex = usePlayerStore((state) => state.jumpToLazyQueueIndex);

  // Drag handlers for regular queue mode
  const handleDragStart = useCallback((index: number, e: React.DragEvent) => {
    setDraggedIndex(index);
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', String(index));
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent, targetIndex: number) => {
    // Internal reorder drag (regular mode only)
    if (draggedIndex !== null) {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      if (targetIndex !== draggedIndex) {
        setDropTargetIndex(targetIndex);
      }
      return;
    }
    // External track drop — show position indicator
    if (e.dataTransfer.types.includes('application/track-id')) {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'copy';
      setDropTargetIndex(targetIndex);
    }
  }, [draggedIndex]);

  const handleDragLeave = useCallback(() => {
    setDropTargetIndex(null);
  }, []);

  const handleDrop = useCallback((targetIndex: number) => {
    if (draggedIndex === null || draggedIndex === targetIndex) {
      setDraggedIndex(null);
      setDropTargetIndex(null);
      return;
    }

    reorderQueue(draggedIndex, targetIndex);
    setDraggedIndex(null);
    setDropTargetIndex(null);
  }, [draggedIndex, reorderQueue]);

  const handleDragEnd = useCallback(() => {
    setDraggedIndex(null);
    setDropTargetIndex(null);
  }, []);

  // Handle external track drop at a specific queue position
  const handleExternalDropAtPosition = useCallback(async (e: React.DragEvent, displayIndex: number) => {
    e.preventDefault();
    setDropTargetIndex(null);
    setIsDragOver(false);

    const trackId = e.dataTransfer.getData('application/track-id');
    if (!trackId) return;

    try {
      const tracks = await tracksApi.getBatch([trackId]);
      if (tracks.length > 0) {
        let insertIdx: number;
        if (isLazyMode) {
          // displayIndex 0 = current track at lazyQueueIndex, insert after hovered item
          insertIdx = lazyQueueIndex + displayIndex + 1;
        } else {
          // In regular mode, insert after the hovered item
          insertIdx = displayIndex + 1;
        }
        addToQueue(tracks[0], insertIdx);
        onTrackDropped?.(trackId);
      }
    } catch (error) {
      log.error('Failed to add track to queue:', error);
    }
  }, [addToQueue, isLazyMode, lazyQueueIndex, queue, onTrackDropped]);

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
  const handleTrackClick = useCallback((displayIndex: number) => {
    if (isLazyMode) {
      if (displayIndex === 0 && currentTrack) {
        // Current track: toggle play/pause
        setIsPlaying(!isPlaying);
      } else if (displayIndex > 0) {
        // Upcoming track: jump to it
        jumpToLazyQueueIndex(lazyQueueIndex + displayIndex);
      }
    } else {
      jumpToQueueIndex(displayIndex);
    }
  }, [isLazyMode, currentTrack, isPlaying, setIsPlaying, jumpToQueueIndex, jumpToLazyQueueIndex, lazyQueueIndex]);

  // Handle removing a track from queue
  const handleRemoveTrack = useCallback((queueId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    removeFromQueue(queueId);
  }, [removeFromQueue]);

  // Handle clearing the entire queue
  const handleClearAll = useCallback(() => {
    if (isLazyMode) {
      exitLazyMode();
    } else {
      clearQueue();
    }
  }, [isLazyMode, exitLazyMode, clearQueue]);

  const formatDuration = (seconds: number | null) => {
    if (!seconds) return '--:--';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  // Build display tracks based on mode
  let displayTracks: { track: Track; queueId: string; isCurrent: boolean }[] = [];
  let totalCount = 0;

  if (isLazyMode) {
    // In lazy mode, show current track + prefetched tracks
    totalCount = lazyQueueIds.length;

    // Add current track if available
    if (currentTrack) {
      displayTracks.push({
        track: currentTrack,
        queueId: `lazy-${lazyQueueIndex}`,
        isCurrent: true,
      });
    }

    // Add prefetched upcoming tracks
    for (let i = lazyQueueIndex + 1; i < Math.min(lazyQueueIndex + 11, lazyQueueIds.length); i++) {
      const trackId = lazyQueueIds[i];
      const prefetched = prefetchedTracks.get(trackId);
      if (prefetched) {
        displayTracks.push({
          track: prefetched,
          queueId: `lazy-${i}`,
          isCurrent: false,
        });
      }
    }
  } else {
    // Regular queue mode - show all tracks
    totalCount = queue.length;
    displayTracks = queue.map((item, index) => ({
      track: item.track,
      queueId: item.queueId,
      isCurrent: index === queueIndex,
    }));
  }

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

        {/* Lazy mode info banner */}
        {isLazyMode && (
          <div className={`mt-3 px-3 py-2 rounded-lg text-sm ${
            resolvedTheme === 'light'
              ? 'bg-green-50 text-green-700 border border-green-200'
              : 'bg-green-900/20 text-green-400 border border-green-800'
          }`}>
            <div className="flex items-center gap-2">
              <Shuffle className="w-4 h-4" />
              <span>Shuffling {totalCount.toLocaleString()} tracks from your library</span>
            </div>
            <p className="mt-1 text-xs opacity-75">
              Showing current track and next {displayTracks.length - 1} upcoming tracks
            </p>
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
          <div className="p-2 space-y-1">
            {displayTracks.map((item, displayIndex) => {
              const { track, queueId, isCurrent } = item;
              const actualIndex = isLazyMode ? displayIndex : queue.findIndex(q => q.queueId === queueId);
              const isDragged = draggedIndex === actualIndex;
              const isDropTarget = dropTargetIndex === displayIndex;

              return (
                <div
                  key={queueId}
                  ref={isCurrent ? currentTrackRef : undefined}
                  draggable={!isLazyMode}
                  onDragStart={(e) => !isLazyMode && handleDragStart(actualIndex, e)}
                  onDragOver={(e) => handleDragOver(e, displayIndex)}
                  onDragLeave={handleDragLeave}
                  onDrop={(e) => {
                    if (draggedIndex !== null && !isLazyMode) {
                      handleDrop(actualIndex);
                    } else if (e.dataTransfer.types.includes('application/track-id')) {
                      e.stopPropagation();
                      handleExternalDropAtPosition(e, displayIndex);
                    }
                  }}
                  onDragEnd={handleDragEnd}
                  onClick={() => handleTrackClick(actualIndex)}
                  className={`group flex items-center gap-3 p-3 rounded-lg cursor-pointer transition-all ${
                    isCurrent
                      ? resolvedTheme === 'light'
                        ? 'bg-green-50 border border-green-200'
                        : 'bg-green-900/20 border border-green-800'
                      : resolvedTheme === 'light'
                        ? 'hover:bg-zinc-100'
                        : 'hover:bg-zinc-800/50'
                  } ${isDragged ? 'opacity-50' : ''} ${isDropTarget ? 'border-t-2 border-green-500' : ''}`}
                >
                  {/* Drag handle (regular mode only) */}
                  {!isLazyMode && (
                    <div className={`flex-shrink-0 cursor-grab active:cursor-grabbing transition-opacity ${
                      'opacity-0 group-hover:opacity-50 hover:!opacity-100'
                    }`}>
                      <GripVertical className="w-4 h-4 text-zinc-500" />
                    </div>
                  )}

                  {/* Play indicator / number */}
                  <div className="w-8 text-center flex-shrink-0">
                    {isCurrent && isPlaying ? (
                      <>
                        <div className="group-hover:hidden flex justify-center gap-0.5">
                          <div className="w-0.5 h-3 bg-green-500 animate-pulse" />
                          <div className="w-0.5 h-3 bg-green-500 animate-pulse [animation-delay:0.2s]" />
                          <div className="w-0.5 h-3 bg-green-500 animate-pulse [animation-delay:0.4s]" />
                        </div>
                        <Pause
                          className="hidden group-hover:block w-4 h-4 mx-auto text-green-500"
                          fill="currentColor"
                        />
                      </>
                    ) : isCurrent ? (
                      <>
                        <span className="group-hover:hidden text-sm text-green-500 font-medium">
                          {isLazyMode ? '•' : displayIndex + 1}
                        </span>
                        <Play
                          className="hidden group-hover:block w-4 h-4 mx-auto text-green-500"
                          fill="currentColor"
                        />
                      </>
                    ) : (
                      <>
                        <span className="group-hover:hidden text-sm text-zinc-500">
                          {isLazyMode ? '•' : displayIndex + 1}
                        </span>
                        <Play
                          className="hidden group-hover:block w-4 h-4 mx-auto"
                          fill="currentColor"
                        />
                      </>
                    )}
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

                  {/* Remove button (regular mode only) */}
                  {!isLazyMode && (
                    <button
                      onClick={(e) => handleRemoveTrack(queueId, e)}
                      className="p-1.5 rounded-lg opacity-0 group-hover:opacity-100 transition-opacity hover:bg-zinc-700/50"
                      title="Remove from queue"
                    >
                      <X className="w-4 h-4 text-zinc-400 hover:text-red-400" />
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
