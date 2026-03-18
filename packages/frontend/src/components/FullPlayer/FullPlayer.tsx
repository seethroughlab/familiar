import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Play,
  Pause,
  SkipBack,
  SkipForward,
  ChevronDown,
  Volume2,
  VolumeX,
  Shuffle,
  Repeat,
  Music,
  Loader2,
  Maximize,
  Minimize,
  ListX,
  EllipsisVertical,
} from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';
import { usePlayerStore } from '../../stores/playerStore';
import { useSelectionStore } from '../../stores/selectionStore';
import { useVisualizerStore } from '../../stores/visualizerStore';
import { useAudioControls } from '../../hooks/useAudioControls';
import { useAppNavigation } from '../../hooks/useAppNavigation';
import { tracksApi, type LyricLine } from '../../api';
import { useUIStore } from '../../stores/uiStore';
import { AudioVisualizer, VisualizerPicker } from '../Visualizer';
import { EffectsQuickAccess } from './EffectsQuickAccess';
import { TrackContextMenu } from '../Library/TrackContextMenu';
import type { ContextMenuState } from '../Library/types';
import { initialContextMenuState } from '../Library/types';
import { useArtworkPrefetch } from '../../hooks/useArtworkPrefetch';
import { useFavorites } from '../../hooks/useFavorites';
import { isMobile } from '../../utils/platform';
import { isVisualizerAvailable } from '../../player/audio/engineInstance';
import { VISUALIZER_IDS } from '../Visualizer/constants';

function formatTime(seconds: number): string {
  if (!seconds || !isFinite(seconds)) return '0:00';
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

interface FullPlayerProps {
  isOpen: boolean;
  onClose: () => void;
}

export function FullPlayer({ isOpen, onClose }: FullPlayerProps) {
  const [imageError, setImageError] = useState(false);
  const [lyrics, setLyrics] = useState<LyricLine[] | null>(null);
  const [contextMenu, setContextMenu] = useState<ContextMenuState>(initialContextMenuState);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [controlsVisible, setControlsVisible] = useState(true);
  const containerRef = useRef<HTMLDivElement>(null);
  const hideTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const { navigateToArtist, navigateToAlbum } = useAppNavigation();

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

  const { seek, togglePlayPause } = useAudioControls();
  const { isFavorite, toggle: toggleFavorite } = useFavorites();
  const { visualizerId } = useVisualizerStore();
  const isMusicVideo = visualizerId === VISUALIZER_IDS.MUSIC_VIDEO;

  // Prefetch artwork for the current track
  const prefetchArtwork = useArtworkPrefetch();
  useEffect(() => {
    if (currentTrack) {
      prefetchArtwork(currentTrack.artist, currentTrack.album, currentTrack.id);
    }
  }, [currentTrack, prefetchArtwork]);

  // Context menu handlers
  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    if (!currentTrack) return;
    e.preventDefault();
    setContextMenu({
      isOpen: true,
      track: currentTrack,
      position: { x: e.clientX, y: e.clientY },
    });
  }, [currentTrack]);

  const closeContextMenu = useCallback(() => {
    setContextMenu(initialContextMenuState);
  }, []);

  // Fetch lyrics for visualizer
  useEffect(() => {
    if (!currentTrack) {
      setLyrics(null);
      return;
    }

    tracksApi.getLyrics(currentTrack.id)
      .then(response => {
        if (response.synced && response.lines.length > 0) {
          setLyrics(response.lines);
        } else {
          setLyrics(null);
        }
      })
      .catch(() => setLyrics(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- Only re-run when track ID changes
  }, [currentTrack?.id]);

  // Reset image error when track changes
  useEffect(() => {
    setImageError(false);
  }, [currentTrack?.id]);

  // Swipe-down-to-close handler
  const touchStartRef = useRef<{ y: number; time: number } | null>(null);
  const handleHeaderTouchStart = useCallback((e: React.TouchEvent) => {
    touchStartRef.current = { y: e.touches[0].clientY, time: Date.now() };
  }, []);
  const handleHeaderTouchEnd = useCallback((e: React.TouchEvent) => {
    if (!touchStartRef.current) return;
    const deltaY = e.changedTouches[0].clientY - touchStartRef.current.y;
    const elapsed = Date.now() - touchStartRef.current.time;
    const velocity = deltaY / elapsed;
    if (deltaY > 50 || velocity > 0.3) {
      onClose();
    }
    touchStartRef.current = null;
  }, [onClose]);

  // Fullscreen toggle
  const toggleFullscreen = useCallback(() => {
    if (!document.fullscreenElement) {
      containerRef.current?.requestFullscreen();
    } else {
      document.exitFullscreen();
    }
  }, []);

  // Sync isFullscreen state with browser fullscreen events
  useEffect(() => {
    const handleFullscreenChange = () => {
      const fs = !!document.fullscreenElement;
      setIsFullscreen(fs);
      if (!fs) {
        setControlsVisible(true);
        if (hideTimerRef.current) clearTimeout(hideTimerRef.current);
      }
    };
    document.addEventListener('fullscreenchange', handleFullscreenChange);
    return () => {
      document.removeEventListener('fullscreenchange', handleFullscreenChange);
      if (hideTimerRef.current) clearTimeout(hideTimerRef.current);
    };
  }, []);

  // Auto-hide controls in fullscreen
  const showControls = useCallback(() => {
    if (!isFullscreen) return;
    setControlsVisible(true);
    if (hideTimerRef.current) clearTimeout(hideTimerRef.current);
    hideTimerRef.current = setTimeout(() => setControlsVisible(false), 3000);
  }, [isFullscreen]);

  // Start hide timer when entering fullscreen
  useEffect(() => {
    if (isFullscreen) {
      hideTimerRef.current = setTimeout(() => setControlsVisible(false), 3000);
    }
    return () => {
      if (hideTimerRef.current) clearTimeout(hideTimerRef.current);
    };
  }, [isFullscreen]);

  const progress = duration > 0 ? (currentTime / duration) * 100 : 0;

  const handleSeek = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const percent = (e.clientX - rect.left) / rect.width;
    seek(percent * duration);
  };

  if (!currentTrack) {
    return null;
  }

  const artworkUrl = tracksApi.getArtworkUrl(currentTrack.id);

  return (
    <div
      ref={containerRef}
      onMouseMove={isFullscreen ? showControls : undefined}
      onTouchStart={isFullscreen ? showControls : undefined}
      className={`fixed inset-0 z-50 bg-black flex flex-col overflow-hidden transition-transform duration-300 ease-out ${isOpen ? 'translate-y-0' : 'translate-y-full pointer-events-none'} ${isFullscreen && !controlsVisible ? 'cursor-none' : ''}`}
    >
      {/* Header - includes safe area padding for notch */}
      <div
        className={`absolute top-0 left-0 right-0 z-10 flex items-center justify-between p-4 pt-safe bg-gradient-to-b from-black/80 to-transparent transition-opacity duration-300 ${isFullscreen && !controlsVisible ? 'opacity-0 pointer-events-none' : 'opacity-100'}`}
        onTouchStart={handleHeaderTouchStart}
        onTouchEnd={handleHeaderTouchEnd}
      >
        <button
          onClick={onClose}
          className="p-2 hover:bg-white/10 rounded-full transition-colors"
          aria-label="Close player"
        >
          <ChevronDown className="w-6 h-6" />
        </button>

        {/* Center: visualizer picker + effects */}
        <div className="flex items-center gap-3">
          {isVisualizerAvailable() && <VisualizerPicker />}
          <EffectsQuickAccess />
        </div>

        {!isMobile() && (
          <button
            onClick={toggleFullscreen}
            className="p-2 hover:bg-white/10 rounded-full transition-colors"
            aria-label={isFullscreen ? 'Exit fullscreen' : 'Enter fullscreen'}
          >
            {isFullscreen ? <Minimize className="w-5 h-5" /> : <Maximize className="w-5 h-5" />}
          </button>
        )}
      </div>

      {/* Main content area */}
      <div className="flex-1 relative overflow-hidden">
        {!isVisualizerAvailable() && !isMusicVideo ? (
          <div className="absolute inset-0 flex items-center justify-center p-8 pb-48">
            {imageError ? (
              <div className="w-72 h-72 sm:w-80 sm:h-80 bg-zinc-800 rounded-2xl flex items-center justify-center shadow-2xl">
                <Music className="w-24 h-24 text-zinc-600" />
              </div>
            ) : (
              <img
                src={artworkUrl}
                alt="Album art"
                className="w-72 h-72 sm:w-80 sm:h-80 rounded-2xl shadow-2xl object-cover"
                onError={() => setImageError(true)}
              />
            )}
          </div>
        ) : (
          <AudioVisualizer
            track={currentTrack}
            artworkUrl={artworkUrl}
            lyrics={lyrics}
            isPlaying={isPlaying}
            className="absolute inset-0"
          />
        )}
      </div>

      {/* Album art thumbnail - z-20 to render above controls gradient */}
      {(isVisualizerAvailable() || isMusicVideo) && !(isFullscreen && !controlsVisible) && (
        <div className="absolute bottom-80 left-8 z-20">
          {imageError ? (
            <div className="w-24 h-24 bg-zinc-800 rounded-lg flex items-center justify-center shadow-2xl">
              <Music className="w-12 h-12 text-zinc-600" />
            </div>
          ) : (
            <img
              src={artworkUrl}
              alt="Album art"
              className="w-24 h-24 rounded-lg shadow-2xl object-cover"
              onError={() => setImageError(true)}
            />
          )}
        </div>
      )}

      {/* Bottom controls - includes safe area padding for home indicator */}
      <div className={`absolute bottom-0 left-0 right-0 z-10 bg-gradient-to-t from-black via-black/95 to-transparent p-4 pt-8 sm:p-6 sm:pt-16 transition-opacity duration-300 ${isFullscreen && !controlsVisible ? 'opacity-0 pointer-events-none' : 'opacity-100'}`} style={{ paddingBottom: 'calc(1.5rem + env(safe-area-inset-bottom, 0px))' }}>
        {/* Track info - right-click for context menu */}
        <div
          className="text-center mb-3 sm:mb-6"
          onContextMenu={handleContextMenu}
        >
          <div className="flex items-center justify-center gap-2">
            <h2 className="text-xl sm:text-2xl font-bold truncate">{currentTrack.title || 'Unknown'}</h2>
            <button
              onClick={handleContextMenu}
              className="p-1.5 text-zinc-400 hover:text-white hover:bg-white/10 rounded-full transition-colors flex-shrink-0"
              aria-label="More options"
            >
              <EllipsisVertical className="w-5 h-5" />
            </button>
          </div>
          {currentTrack.artist ? (
            <button
              onClick={() => { onClose(); navigateToArtist(currentTrack.artist!); }}
              className="block text-lg text-zinc-400 hover:text-zinc-200 hover:underline transition-colors"
            >
              {currentTrack.artist}
            </button>
          ) : (
            <p className="text-lg text-zinc-400">Unknown</p>
          )}
          {currentTrack.album ? (
            <button
              onClick={() => { onClose(); navigateToAlbum(currentTrack.artist!, currentTrack.album!); }}
              className="block text-sm text-zinc-500 hover:text-zinc-300 hover:underline transition-colors"
            >
              {currentTrack.album}
            </button>
          ) : null}
        </div>

        {/* Progress bar */}
        <div className="mb-3 sm:mb-6">
          <div
            className="py-3 cursor-pointer group"
            onClick={handleSeek}
          >
            <div className="h-1.5 bg-zinc-700 rounded-full">
              <div
                className="h-full bg-white rounded-full relative group-hover:bg-green-500 transition-colors"
                style={{ width: `${progress}%` }}
              >
                <div className="absolute right-0 top-1/2 -translate-y-1/2 w-4 h-4 bg-white rounded-full opacity-0 group-hover:opacity-100 transition-opacity shadow-lg" />
              </div>
            </div>
          </div>
          <div className="flex justify-between text-sm text-zinc-400 mt-2">
            <span>{formatTime(currentTime)}</span>
            <span>{formatTime(duration)}</span>
          </div>
        </div>

        {/* Controls */}
        <div className="flex items-center justify-center gap-3 sm:gap-6">
          <button
            onClick={toggleShuffle}
            className={`p-3 rounded-full transition-colors ${
              shuffle ? 'text-green-500' : 'text-zinc-400 hover:text-white'
            }`}
            aria-label={shuffle ? 'Disable shuffle' : 'Enable shuffle'}
            aria-pressed={shuffle}
          >
            <Shuffle className="w-5 h-5" />
          </button>

          <button
            onClick={playPrevious}
            className="p-3 hover:bg-white/10 rounded-full transition-colors"
            aria-label="Previous track"
          >
            <SkipBack className="w-7 h-7" fill="currentColor" />
          </button>

          <button
            onClick={togglePlayPause}
            className="p-5 bg-white text-black rounded-full hover:scale-105 transition-transform shadow-lg"
            aria-label={isLoadingAudio ? 'Loading' : isPlaying ? 'Pause' : 'Play'}
          >
            {isLoadingAudio ? (
              <Loader2 className="w-8 h-8 animate-spin" />
            ) : isPlaying ? (
              <Pause className="w-8 h-8" fill="currentColor" />
            ) : (
              <Play className="w-8 h-8" fill="currentColor" />
            )}
          </button>

          <button
            onClick={playNext}
            className="p-3 hover:bg-white/10 rounded-full transition-colors"
            aria-label="Next track"
          >
            <SkipForward className="w-7 h-7" fill="currentColor" />
          </button>

          <button
            onClick={toggleRepeat}
            className={`p-3 rounded-full transition-colors ${
              repeat !== 'off' ? 'text-green-500' : 'text-zinc-400 hover:text-white'
            }`}
            aria-label={`Repeat: ${repeat}`}
            aria-pressed={repeat !== 'off'}
          >
            <Repeat className="w-5 h-5" />
          </button>

          {!isMobile() && (
            <button
              onClick={toggleConsume}
              className={`p-3 rounded-full transition-colors ${
                consume ? 'text-green-500' : 'text-zinc-400 hover:text-white'
              }`}
              aria-label={consume ? 'Disable consume mode' : 'Enable consume mode'}
              aria-pressed={consume}
              title="Consume: remove tracks after playing"
            >
              <ListX className="w-5 h-5" />
            </button>
          )}
        </div>

        {/* Volume - hidden on mobile where hardware buttons control volume */}
        {!isMobile() && (
          <div className="flex items-center justify-center gap-3 mt-6">
            <button
              onClick={() => setVolume(volume > 0 ? 0 : 1)}
              className="p-2 text-zinc-400 hover:text-white transition-colors"
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
              onChange={(e) => setVolume(parseFloat(e.target.value))}
              className="w-24 sm:w-32 accent-white"
              aria-label="Volume"
            />
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
            // Already playing this track
          }}
          onQueue={() => {
            if (contextMenu.track) {
              addToQueue(contextMenu.track);
            }
          }}
          onGoToArtist={() => {
            if (contextMenu.track?.artist) {
              onClose();
              navigateToArtist(contextMenu.track.artist);
            }
          }}
          onGoToAlbum={() => {
            if (contextMenu.track?.artist && contextMenu.track?.album) {
              onClose();
              navigateToAlbum(contextMenu.track.artist, contextMenu.track.album);
            }
          }}
          onToggleSelect={() => {
            // Not applicable in full player
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
              onClose();
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
