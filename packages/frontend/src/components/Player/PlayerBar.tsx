import { useState, useCallback, useEffect, useRef } from 'react';
import { Play, Pause, SkipBack, SkipForward, Volume2, VolumeX, Music, ChevronUp, Shuffle, Repeat, Loader2, ListX, ListMusic, MessageSquare } from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';
import { usePlayerStore } from '../../stores/playerStore';
import { useSelectionStore } from '../../stores/selectionStore';
import { useShuffleWeightStore } from '../../stores/shuffleWeightStore';
import { useAudioControls } from '../../hooks/useAudioControls';
import { useAppNavigation } from '../../hooks/useAppNavigation';
import { tracksApi } from '../../api';
import { TrackContextMenu } from '../Library/TrackContextMenu';
import type { ContextMenuState } from '../Library/types';
import { initialContextMenuState } from '../Library/types';
import { useArtworkPrefetch } from '../../hooks/useArtworkPrefetch';
import { useFavorites } from '../../hooks/useFavorites';
import { useUIStore } from '../../stores/uiStore';
import { ShuffleWeightPopover } from './ShuffleWeightPopover';

interface PlayerBarProps {
  onExpandClick?: () => void;
  onQueueToggle?: () => void;
  isQueueOpen?: boolean;
  onChatToggle?: () => void;
  isChatOpen?: boolean;
}

function formatTime(seconds: number): string {
  if (!seconds || !isFinite(seconds)) return '0:00';
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

function AlbumArt({ trackId }: { trackId: string }) {
  const [hasError, setHasError] = useState(false);
  const artworkUrl = tracksApi.getArtworkUrl(trackId);

  useEffect(() => {
    setHasError(false);
  }, [trackId]);

  if (hasError) {
    return (
      <div className="w-12 h-12 bg-zinc-800 rounded flex-shrink-0 flex items-center justify-center">
        <Music className="w-6 h-6 text-zinc-600" />
      </div>
    );
  }

  return (
    <img
      src={artworkUrl}
      alt="Album art"
      className="w-12 h-12 bg-zinc-800 rounded flex-shrink-0 object-cover"
      onError={() => setHasError(true)}
    />
  );
}

export function PlayerBar({
  onExpandClick,
  onQueueToggle,
  isQueueOpen = false,
  onChatToggle,
  isChatOpen = false,
}: PlayerBarProps) {
  const { currentTrack, isPlaying, isLoadingAudio, currentTime, duration, volume, shuffle, repeat, consume } = usePlayerStore(
    useShallow((s) => ({
      currentTrack: s.currentTrack, isPlaying: s.isPlaying, isLoadingAudio: s.isLoadingAudio,
      currentTime: s.currentTime, duration: s.duration, volume: s.volume,
      shuffle: s.shuffle, repeat: s.repeat, consume: s.consume,
    }))
  );
  const setVolume = usePlayerStore((s) => s.setVolume);
  const playNext = usePlayerStore((s) => s.playNext);
  const playPrevious = usePlayerStore((s) => s.playPrevious);
  const toggleShuffle = usePlayerStore((s) => s.toggleShuffle);
  const toggleRepeat = usePlayerStore((s) => s.toggleRepeat);
  const toggleConsume = usePlayerStore((s) => s.toggleConsume);
  const addToQueue = usePlayerStore((s) => s.addToQueue);

  const weightedEnabled = useShuffleWeightStore((s) => s.enabled);

  const { seek, togglePlayPause } = useAudioControls();
  const { navigateToArtist, navigateToAlbum } = useAppNavigation();
  const { isFavorite, toggle: toggleFavorite } = useFavorites();

  // Shuffle weight popover (long-press / right-click)
  const shuffleButtonRef = useRef<HTMLButtonElement>(null);
  const [shufflePopoverOpen, setShufflePopoverOpen] = useState(false);
  const longPressTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleShufflePointerDown = useCallback(() => {
    longPressTimerRef.current = setTimeout(() => {
      setShufflePopoverOpen(true);
      longPressTimerRef.current = null;
    }, 500);
  }, []);

  const handleShufflePointerUp = useCallback(() => {
    if (longPressTimerRef.current) {
      clearTimeout(longPressTimerRef.current);
      longPressTimerRef.current = null;
    }
  }, []);

  const handleShuffleContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setShufflePopoverOpen(true);
  }, []);

  // Prefetch artwork for the current track
  const prefetchArtwork = useArtworkPrefetch();
  useEffect(() => {
    if (currentTrack) {
      prefetchArtwork(currentTrack.artist, currentTrack.album, currentTrack.id);
    }
  }, [currentTrack, prefetchArtwork]);

  // Context menu state
  const [contextMenu, setContextMenu] = useState<ContextMenuState>(initialContextMenuState);

  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    if (currentTrack) {
      setContextMenu({
        isOpen: true,
        track: currentTrack,
        position: { x: e.clientX, y: e.clientY },
      });
    }
  }, [currentTrack]);

  const closeContextMenu = useCallback(() => {
    setContextMenu(initialContextMenuState);
  }, []);

  const progress = duration > 0 ? (currentTime / duration) * 100 : 0;

  const handleSeek = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const percent = (e.clientX - rect.left) / rect.width;
    seek(percent * duration);
  };

  const handleVolumeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setVolume(parseFloat(e.target.value));
  };

  // Swipe-up-to-expand handler for mobile
  const touchStartRef = useRef<{ y: number; time: number } | null>(null);
  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    touchStartRef.current = { y: e.touches[0].clientY, time: Date.now() };
  }, []);
  const handleTouchEnd = useCallback((e: React.TouchEvent) => {
    if (!touchStartRef.current || !onExpandClick) return;
    const deltaY = touchStartRef.current.y - e.changedTouches[0].clientY;
    const elapsed = Date.now() - touchStartRef.current.time;
    const velocity = deltaY / elapsed;
    if (deltaY > 50 || velocity > 0.3) {
      onExpandClick();
    }
    touchStartRef.current = null;
  }, [onExpandClick]);

  const hasTrack = !!currentTrack;

  return (
    <div className="shrink-0 bg-zinc-900 border-t border-zinc-800 z-20 pb-safe-bottom-desktop">
      {/* Mobile layout: two rows - track info + play, then progress bar */}
      <div
        className="sm:hidden"
        onTouchStart={handleTouchStart}
        onTouchEnd={handleTouchEnd}
      >
        {/* Drag handle pill */}
        <div className="flex justify-center pt-1.5">
          <div className="w-8 h-1 bg-zinc-600 rounded-full" />
        </div>
        {/* Row 1: Album art + Track info + ChevronUp + Play/Pause */}
        <div className="flex items-center gap-3 px-4 pt-1 pb-1">
          <button
            onClick={onExpandClick}
            onContextMenu={handleContextMenu}
            className="flex items-center gap-3 flex-1 min-w-0 text-left"
            aria-label="Expand player"
            disabled={!hasTrack}
          >
            {currentTrack ? (
              <AlbumArt trackId={currentTrack.id} />
            ) : (
              <div className="w-12 h-12 bg-zinc-800 rounded flex-shrink-0 flex items-center justify-center">
                <Music className="w-6 h-6 text-zinc-600" />
              </div>
            )}
            <div className="min-w-0 flex-1">
              {currentTrack ? (
                <>
                  <div className="flex items-center gap-1.5">
                    <span data-testid="current-track-title" className="font-medium truncate">{currentTrack.title || 'Unknown'}</span>
                  </div>
                  <div className="text-sm text-zinc-400 truncate">{currentTrack.artist || 'Unknown'}</div>
                </>
              ) : (
                <div className="text-sm text-zinc-500">No track selected</div>
              )}
            </div>
          </button>
          {hasTrack && (
            <ChevronUp
              className="w-5 h-5 text-zinc-500 flex-shrink-0"
              onClick={onExpandClick}
            />
          )}
          <button
            data-testid="play-pause-mobile"
            onClick={togglePlayPause}
            className={`p-3 rounded-full flex-shrink-0 ${hasTrack ? 'bg-white text-black' : 'bg-zinc-700 text-zinc-500'}`}
            aria-label={isLoadingAudio ? 'Loading' : isPlaying ? 'Pause' : 'Play'}
            disabled={!hasTrack}
          >
            {isLoadingAudio ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : isPlaying ? (
              <Pause className="w-5 h-5" fill="currentColor" />
            ) : (
              <Play className="w-5 h-5" fill="currentColor" />
            )}
          </button>
        </div>
        {/* Row 2: Progress bar (full width, tappable) */}
        <div className="px-4 pb-2">
          <div
            data-testid="progress-bar-mobile"
            className={`py-2 ${hasTrack ? 'cursor-pointer' : ''}`}
            onClick={hasTrack ? handleSeek : undefined}
          >
            <div className="h-1 bg-zinc-700 rounded-full">
              <div
                className="h-full bg-white rounded-full"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        </div>
      </div>

      {/* Desktop layout: single row with all controls */}
      <div className="hidden sm:flex h-20 max-w-screen-2xl mx-auto px-4 items-center gap-4">
        {/* Track info - clickable to expand, right-click for context menu */}
        <button
          onClick={hasTrack ? onExpandClick : undefined}
          onContextMenu={handleContextMenu}
          className={`flex items-center gap-3 w-64 min-w-0 text-left rounded-lg p-1 -ml-1 transition-colors group ${hasTrack ? 'hover:bg-zinc-800/50' : ''}`}
          aria-label="Expand player"
          disabled={!hasTrack}
        >
          {currentTrack ? (
            <AlbumArt trackId={currentTrack.id} />
          ) : (
            <div className="w-12 h-12 bg-zinc-800 rounded flex-shrink-0 flex items-center justify-center">
              <Music className="w-6 h-6 text-zinc-600" />
            </div>
          )}
          <div className="min-w-0 flex-1">
            {currentTrack ? (
              <>
                <div className="flex items-center gap-1.5">
                  <span data-testid="current-track-title" className="font-medium truncate">{currentTrack.title || 'Unknown'}</span>
                </div>
                <div className="text-sm text-zinc-400 truncate">{currentTrack.artist || 'Unknown'}</div>
              </>
            ) : (
              <div className="text-sm text-zinc-500">No track selected</div>
            )}
          </div>
        </button>

        {/* Standalone expand button */}
        <button
          onClick={onExpandClick}
          className={`p-2 rounded-full transition-colors ${hasTrack ? 'text-zinc-400 hover:text-white hover:bg-zinc-800' : 'text-zinc-600'}`}
          aria-label="Expand player"
          title="Expand player (F)"
          disabled={!hasTrack}
        >
          <ChevronUp className="w-5 h-5" />
        </button>

        {/* Controls */}
        <div className="flex-1 flex flex-col items-center gap-1">
          <div className="flex items-center gap-4">
            <div className="relative">
              <button
                ref={shuffleButtonRef}
                onClick={toggleShuffle}
                onContextMenu={handleShuffleContextMenu}
                onPointerDown={handleShufflePointerDown}
                onPointerUp={handleShufflePointerUp}
                onPointerLeave={handleShufflePointerUp}
                className={`p-2 rounded-full transition-colors ${
                  !hasTrack ? 'text-zinc-600' : shuffle && weightedEnabled ? 'text-amber-400' : shuffle ? 'text-green-500' : 'text-zinc-400 hover:text-white'
                }`}
                aria-label={shuffle ? 'Disable shuffle' : 'Enable shuffle'}
                aria-pressed={shuffle}
                disabled={!hasTrack}
              >
                <Shuffle className="w-4 h-4" />
              </button>
              <ShuffleWeightPopover
                isOpen={shufflePopoverOpen}
                onClose={() => setShufflePopoverOpen(false)}
                buttonRef={shuffleButtonRef}
                position="above"
              />
            </div>
            <button
              data-testid="prev-track"
              onClick={playPrevious}
              className={`p-2 rounded-full transition-colors ${hasTrack ? 'hover:bg-zinc-800' : 'text-zinc-600'}`}
              aria-label="Previous track"
              disabled={!hasTrack}
            >
              <SkipBack className="w-5 h-5" />
            </button>
            <button
              data-testid="play-pause"
              onClick={togglePlayPause}
              className={`p-3 rounded-full transition-transform ${hasTrack ? 'bg-white text-black hover:scale-105' : 'bg-zinc-700 text-zinc-500'}`}
              aria-label={isLoadingAudio ? 'Loading' : isPlaying ? 'Pause' : 'Play'}
              disabled={!hasTrack}
            >
              {isLoadingAudio ? (
                <Loader2 className="w-5 h-5 animate-spin" />
              ) : isPlaying ? (
                <Pause className="w-5 h-5" fill="currentColor" />
              ) : (
                <Play className="w-5 h-5" fill="currentColor" />
              )}
            </button>
            <button
              data-testid="next-track"
              onClick={playNext}
              className={`p-2 rounded-full transition-colors ${hasTrack ? 'hover:bg-zinc-800' : 'text-zinc-600'}`}
              aria-label="Next track"
              disabled={!hasTrack}
            >
              <SkipForward className="w-5 h-5" />
            </button>
            <button
              onClick={toggleRepeat}
              className={`p-2 rounded-full transition-colors relative ${
                !hasTrack ? 'text-zinc-600' : repeat !== 'off' ? 'text-green-500' : 'text-zinc-400 hover:text-white'
              }`}
              aria-label={`Repeat: ${repeat}`}
              aria-pressed={repeat !== 'off'}
              disabled={!hasTrack}
            >
              <Repeat className="w-4 h-4" />
              {repeat === 'one' && (
                <span className="absolute -top-0.5 -right-0.5 text-[8px] font-bold">1</span>
              )}
            </button>
            <button
              onClick={toggleConsume}
              className={`p-2 rounded-full transition-colors ${
                !hasTrack ? 'text-zinc-600' : consume ? 'text-green-500' : 'text-zinc-400 hover:text-white'
              }`}
              aria-label={consume ? 'Disable consume mode' : 'Enable consume mode'}
              aria-pressed={consume}
              title="Consume: remove tracks after playing"
              disabled={!hasTrack}
            >
              <ListX className="w-4 h-4" />
            </button>
          </div>

          {/* Progress bar */}
          <div className="w-full max-w-xl flex items-center gap-2">
            <span className="text-xs text-zinc-400 w-10 text-right">
              {formatTime(currentTime)}
            </span>
            <div
              data-testid="progress-bar"
              className={`flex-1 py-2 group ${hasTrack ? 'cursor-pointer' : ''}`}
              onClick={hasTrack ? handleSeek : undefined}
            >
              <div className="h-1 bg-zinc-700 rounded-full">
                <div
                  className={`h-full rounded-full relative transition-colors ${hasTrack ? 'bg-white group-hover:bg-green-500' : 'bg-zinc-600'}`}
                  style={{ width: `${progress}%` }}
                >
                  {hasTrack && (
                    <div className="absolute right-0 top-1/2 -translate-y-1/2 w-3 h-3 bg-white rounded-full opacity-0 group-hover:opacity-100 transition-opacity" />
                  )}
                </div>
              </div>
            </div>
            <span className="text-xs text-zinc-400 w-10">
              {formatTime(duration)}
            </span>
          </div>
        </div>

        {/* Volume */}
        <div className="flex items-center gap-2 w-32">
          <button
            onClick={() => setVolume(volume > 0 ? 0 : 1)}
            className="p-2 hover:bg-zinc-800 rounded-full transition-colors"
            aria-label={volume === 0 ? 'Unmute' : 'Mute'}
          >
            {volume === 0 ? (
              <VolumeX className="w-5 h-5" />
            ) : (
              <Volume2 className="w-5 h-5" />
            )}
          </button>
          <input
            type="range"
            min="0"
            max="1"
            step="0.01"
            value={volume}
            onChange={handleVolumeChange}
            className="w-full accent-white"
            aria-label="Volume"
          />
        </div>

        {/* Queue toggle */}
        {onQueueToggle && (
          <button
            onClick={onQueueToggle}
            className={`p-2 rounded-full transition-colors ${
              isQueueOpen ? 'text-green-500' : 'text-zinc-400 hover:text-white hover:bg-zinc-800'
            }`}
            aria-label={isQueueOpen ? 'Close queue' : 'Open queue'}
            title="Queue"
          >
            <ListMusic className="w-5 h-5" />
          </button>
        )}

        {/* Chat toggle */}
        {onChatToggle && (
          <button
            onClick={onChatToggle}
            className={`p-2 rounded-full transition-colors ${
              isChatOpen ? 'text-green-500' : 'text-zinc-400 hover:text-white hover:bg-zinc-800'
            }`}
            aria-label={isChatOpen ? 'Close chat' : 'Open chat'}
            title="AI Assistant"
          >
            <MessageSquare className="w-5 h-5" />
          </button>
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
            // Already playing this track
          }}
          onQueue={() => {
            if (contextMenu.track) {
              addToQueue(contextMenu.track);
            }
          }}
          onGoToArtist={() => {
            if (contextMenu.track?.artist) {
              navigateToArtist(contextMenu.track.artist);
            }
          }}
          onGoToAlbum={() => {
            if (contextMenu.track?.artist && contextMenu.track?.album) {
              navigateToAlbum(contextMenu.track.artist, contextMenu.track.album);
            }
          }}
          onToggleSelect={() => {
            // Not applicable in player bar
          }}
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
            if (contextMenu.track) {
              toggleFavorite(contextMenu.track.id);
            }
          }}
        />
      )}
    </div>
  );
}
