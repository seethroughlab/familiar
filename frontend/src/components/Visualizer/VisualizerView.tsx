import { useState, useRef, useEffect } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { Maximize2, Minimize2, Music } from 'lucide-react';
import { usePlayerStore } from '../../stores/playerStore';
import { useVisualizerStore } from '../../stores/visualizerStore';
import { tracksApi, type LyricLine } from '../../api/client';
import { AudioVisualizer } from './AudioVisualizer';
import { VisualizerPicker } from './VisualizerPicker';
import { setVisualizerVisible } from '../../hooks/useAudioEngine';

export function VisualizerView() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [lyrics, setLyrics] = useState<LyricLine[] | null>(null);
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const { currentTrack, currentTime, duration, isPlaying } = usePlayerStore();
  const { visualizerId, setVisualizerId } = useVisualizerStore();

  // Notify audio engine when visualizer is visible (for iOS hybrid mode)
  useEffect(() => {
    setVisualizerVisible(true);
    return () => setVisualizerVisible(false);
  }, []);

  // Sync visualizer type with URL
  const urlVisualizerType = searchParams.get('type');

  // On mount, apply URL param to store if present
  useEffect(() => {
    if (urlVisualizerType && urlVisualizerType !== visualizerId) {
      setVisualizerId(urlVisualizerType);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- Only run on mount to initialize from URL
  }, []);

  // When visualizer changes in store, update URL
  useEffect(() => {
    const currentUrlType = searchParams.get('type');
    if (visualizerId && visualizerId !== currentUrlType) {
      const newParams = new URLSearchParams(searchParams);
      newParams.set('type', visualizerId);
      // Use navigate to preserve the hash (e.g., #visualizer)
      const paramString = newParams.toString();
      navigate(`?${paramString}${window.location.hash}`, { replace: true });
    }
  }, [visualizerId, searchParams, navigate]);

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

  // Track fullscreen state changes
  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(document.fullscreenElement === containerRef.current);
    };

    document.addEventListener('fullscreenchange', handleFullscreenChange);
    return () => document.removeEventListener('fullscreenchange', handleFullscreenChange);
  }, []);

  // Handle keyboard shortcuts for fullscreen
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // F11 or F key for fullscreen toggle (only when in visualizer view and not in input)
      if ((e.key === 'F11' || (e.key === 'f' && !e.ctrlKey && !e.metaKey)) &&
          !(e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement)) {
        e.preventDefault();
        toggleFullscreen();
      }
      // Escape to exit fullscreen
      if (e.key === 'Escape' && isFullscreen) {
        exitFullscreen();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isFullscreen]);

  const toggleFullscreen = () => {
    if (!containerRef.current) return;

    if (document.fullscreenElement) {
      document.exitFullscreen();
    } else {
      containerRef.current.requestFullscreen();
    }
  };

  const exitFullscreen = () => {
    if (document.fullscreenElement) {
      document.exitFullscreen();
    }
  };

  const artworkUrl = currentTrack ? tracksApi.getArtworkUrl(currentTrack.id) : null;

  // Show placeholder when no track is playing
  if (!currentTrack) {
    return (
      <div data-testid="visualizer-placeholder" className="h-full flex flex-col items-center justify-center text-zinc-500">
        <Music className="w-16 h-16 mb-4" />
        <p className="text-lg">No track playing</p>
        <p className="text-sm mt-2">Play a track to see the visualizer</p>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="relative h-full w-full bg-black overflow-hidden"
    >
      {/* Visualizer */}
      <AudioVisualizer
        track={currentTrack}
        artworkUrl={artworkUrl}
        lyrics={lyrics}
        currentTime={currentTime}
        duration={duration}
        isPlaying={isPlaying}
        features={currentTrack?.features ?? null}
        className="absolute inset-0"
      />

      {/* Controls overlay - visible on hover or when paused */}
      <div className={`absolute inset-0 transition-opacity ${isPlaying ? 'opacity-0 hover:opacity-100' : 'opacity-100'}`}>
        {/* Top bar with visualizer picker and fullscreen button */}
        <div className="absolute top-0 left-0 right-0 p-4 bg-gradient-to-b from-black/60 to-transparent">
          <div className="flex items-center justify-between">
            {/* Track info */}
            <div className="flex items-center gap-3 min-w-0">
              {artworkUrl && (
                <img
                  src={artworkUrl}
                  alt="Album art"
                  className="w-10 h-10 rounded shadow-lg flex-shrink-0"
                />
              )}
              <div className="min-w-0">
                <div className="text-white font-medium truncate">{currentTrack.title}</div>
                <div className="text-zinc-400 text-sm truncate">{currentTrack.artist}</div>
              </div>
            </div>

            {/* Controls */}
            <div className="flex items-center gap-2">
              <VisualizerPicker />
              <button
                onClick={toggleFullscreen}
                className="p-2 hover:bg-white/10 rounded-lg transition-colors text-white"
                title={isFullscreen ? 'Exit fullscreen (F)' : 'Fullscreen (F)'}
              >
                {isFullscreen ? (
                  <Minimize2 className="w-5 h-5" />
                ) : (
                  <Maximize2 className="w-5 h-5" />
                )}
              </button>
            </div>
          </div>
        </div>

        {/* Hint when not fullscreen */}
        {!isFullscreen && (
          <div className="absolute bottom-4 left-1/2 -translate-x-1/2 text-zinc-500 text-sm">
            Press <kbd className="px-1.5 py-0.5 bg-zinc-800 rounded text-xs">F</kbd> for fullscreen
          </div>
        )}
      </div>
    </div>
  );
}
