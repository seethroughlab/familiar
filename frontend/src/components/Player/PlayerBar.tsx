import { useState, useCallback, useEffect, useRef } from 'react';
import { Play, Pause, SkipBack, SkipForward, Volume2, VolumeX, Music, ChevronUp, Shuffle, Repeat, Loader2, Radio } from 'lucide-react';
import { usePlayerStore } from '../../stores/playerStore';
import { useSelectionStore } from '../../stores/selectionStore';
import { useAudioEngine } from '../../hooks/useAudioEngine';
import { useAppNavigation } from '../../hooks/useAppNavigation';
import { tracksApi } from '../../api/client';
import { TrackContextMenu } from '../Library/TrackContextMenu';
import type { ContextMenuState } from '../Library/types';
import { initialContextMenuState } from '../Library/types';
import { useArtworkPrefetch } from '../../hooks/useArtworkPrefetch';
import { useFavorites } from '../../hooks/useFavorites';

interface PlayerBarProps {
  onExpandClick?: () => void;
  // Listening sessions disabled for v0.1.0 - re-enable when signaling server is ready
  // onSessionClick?: () => void;
  // isInSession?: boolean;
  // sessionParticipantCount?: number;
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
  // Listening sessions disabled for v0.1.0
  // onSessionClick,
  // isInSession = false,
  // sessionParticipantCount = 0,
}: PlayerBarProps) {
  const {
    currentTrack,
    isPlaying,
    isLoadingAudio,
    currentTime,
    duration,
    volume,
    setVolume,
    playNext,
    playPrevious,
    shuffle,
    toggleShuffle,
    repeat,
    toggleRepeat,
    addToQueue,
    isPreviewMode,
  } = usePlayerStore();

  const { seek, togglePlayPause } = useAudioEngine();
  const { navigateToArtist, navigateToAlbum } = useAppNavigation();
  const { isFavorite, toggle: toggleFavorite } = useFavorites();

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

  if (!currentTrack) {
    return (
      <div className="fixed bottom-0 left-0 right-0 bg-zinc-900 border-t border-zinc-800 z-20 flex items-center justify-center text-zinc-500 h-20 pb-safe-bottom">
        No track selected
      </div>
    );
  }

  return (
    <div className="fixed bottom-0 left-0 right-0 bg-zinc-900 border-t border-zinc-800 z-20 pb-safe-bottom">
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
          >
            <AlbumArt trackId={currentTrack.id} />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span data-testid="current-track-title" className="font-medium truncate">{currentTrack.title || 'Unknown'}</span>
                {isPreviewMode && (
                  <span className="flex items-center gap-1 px-1.5 py-0.5 text-[10px] bg-amber-500/20 text-amber-400 rounded flex-shrink-0">
                    <Radio className="w-3 h-3" />
                    Preview
                  </span>
                )}
              </div>
              <div className="text-sm text-zinc-400 truncate">{currentTrack.artist || 'Unknown'}</div>
            </div>
          </button>
          <ChevronUp
            className="w-5 h-5 text-zinc-500 flex-shrink-0"
            onClick={onExpandClick}
          />
          <button
            data-testid="play-pause-mobile"
            onClick={togglePlayPause}
            className="p-3 bg-white text-black rounded-full flex-shrink-0"
            aria-label={isLoadingAudio ? 'Loading' : isPlaying ? 'Pause' : 'Play'}
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
            className="py-2 cursor-pointer"
            onClick={handleSeek}
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
          onClick={onExpandClick}
          onContextMenu={handleContextMenu}
          className="flex items-center gap-3 w-64 min-w-0 text-left hover:bg-zinc-800/50 rounded-lg p-1 -ml-1 transition-colors group"
          aria-label="Expand player"
        >
          <AlbumArt trackId={currentTrack.id} />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span data-testid="current-track-title" className="font-medium truncate">{currentTrack.title || 'Unknown'}</span>
              {isPreviewMode && (
                <span className="flex items-center gap-1 px-1.5 py-0.5 text-[10px] bg-amber-500/20 text-amber-400 rounded flex-shrink-0">
                  <Radio className="w-3 h-3" />
                  Preview
                </span>
              )}
            </div>
            <div className="text-sm text-zinc-400 truncate">{currentTrack.artist || 'Unknown'}</div>
          </div>
        </button>

        {/* Standalone expand button */}
        <button
          onClick={onExpandClick}
          className="p-2 hover:bg-zinc-800 rounded-full transition-colors text-zinc-400 hover:text-white"
          aria-label="Expand player"
          title="Expand player (F)"
        >
          <ChevronUp className="w-5 h-5" />
        </button>

        {/* Controls */}
        <div className="flex-1 flex flex-col items-center gap-1">
          <div className="flex items-center gap-4">
            <button
              onClick={toggleShuffle}
              className={`p-2 rounded-full transition-colors ${
                shuffle ? 'text-green-500' : 'text-zinc-400 hover:text-white'
              }`}
              aria-label={shuffle ? 'Disable shuffle' : 'Enable shuffle'}
              aria-pressed={shuffle}
            >
              <Shuffle className="w-4 h-4" />
            </button>
            <button
              data-testid="prev-track"
              onClick={playPrevious}
              className="p-2 hover:bg-zinc-800 rounded-full transition-colors"
              aria-label="Previous track"
            >
              <SkipBack className="w-5 h-5" />
            </button>
            <button
              data-testid="play-pause"
              onClick={togglePlayPause}
              className="p-3 bg-white text-black rounded-full hover:scale-105 transition-transform"
              aria-label={isLoadingAudio ? 'Loading' : isPlaying ? 'Pause' : 'Play'}
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
              className="p-2 hover:bg-zinc-800 rounded-full transition-colors"
              aria-label="Next track"
            >
              <SkipForward className="w-5 h-5" />
            </button>
            <button
              onClick={toggleRepeat}
              className={`p-2 rounded-full transition-colors relative ${
                repeat !== 'off' ? 'text-green-500' : 'text-zinc-400 hover:text-white'
              }`}
              aria-label={`Repeat: ${repeat}`}
              aria-pressed={repeat !== 'off'}
            >
              <Repeat className="w-4 h-4" />
              {repeat === 'one' && (
                <span className="absolute -top-0.5 -right-0.5 text-[8px] font-bold">1</span>
              )}
            </button>
          </div>

          {/* Progress bar */}
          <div className="w-full max-w-xl flex items-center gap-2">
            <span className="text-xs text-zinc-400 w-10 text-right">
              {formatTime(currentTime)}
            </span>
            <div
              data-testid="progress-bar"
              className="flex-1 py-2 cursor-pointer group"
              onClick={handleSeek}
            >
              <div className="h-1 bg-zinc-700 rounded-full">
                <div
                  className="h-full bg-white rounded-full relative group-hover:bg-green-500 transition-colors"
                  style={{ width: `${progress}%` }}
                >
                  <div className="absolute right-0 top-1/2 -translate-y-1/2 w-3 h-3 bg-white rounded-full opacity-0 group-hover:opacity-100 transition-opacity" />
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
            // TODO: Open playlist picker modal
          }}
          onMakePlaylist={() => {
            if (contextMenu.track) {
              const track = contextMenu.track;
              const message = `Make me a playlist based on "${track.title || 'this track'}" by ${track.artist || 'Unknown Artist'}`;
              window.dispatchEvent(new CustomEvent('trigger-chat', { detail: { message } }));
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
