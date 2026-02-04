import { useState, useEffect, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Play,
  Pause,
  SkipBack,
  SkipForward,
  X,
  Volume2,
  VolumeX,
  Shuffle,
  Repeat,
  Music,
  Video,
  Type,
  Compass,
  Loader2,
} from 'lucide-react';
import { usePlayerStore } from '../../stores/playerStore';
import { useSelectionStore } from '../../stores/selectionStore';
import { useAudioEngine } from '../../hooks/useAudioEngine';
import { useAppNavigation } from '../../hooks/useAppNavigation';
import { tracksApi, playlistsApi, type LyricLine } from '../../api/client';
import { AudioVisualizer, VisualizerPicker } from '../Visualizer';
import { LyricsDisplay } from './LyricsDisplay';
import { VideoPlayer } from './VideoPlayer';
import { EffectsQuickAccess } from './EffectsQuickAccess';
import { DiscoveryPanel, useTrackDiscovery, type DiscoveryItem } from '../Discovery';
import { TrackContextMenu } from '../Library/TrackContextMenu';
import type { ContextMenuState } from '../Library/types';
import { initialContextMenuState } from '../Library/types';
import { useArtworkPrefetch } from '../../hooks/useArtworkPrefetch';
import { useFavorites } from '../../hooks/useFavorites';
import type { Track } from '../../types';

type ViewMode = 'visualizer' | 'video' | 'lyrics' | 'discover';

// Discovery tab component using unified Discovery components
function FullPlayerDiscoverTab({
  discoverData,
  loading,
  onGoToArtist,
  onPlayTrack,
  onAddToWishlist,
}: {
  discoverData: {
    similar_tracks: Array<{
      id: string;
      title: string | null;
      artist: string | null;
      album: string | null;
    }>;
    similar_artists: Array<{
      name: string;
      match_score: number;
      in_library: boolean;
      track_count: number | null;
      image_url: string | null;
      lastfm_url: string | null;
      bandcamp_url: string | null;
    }>;
    bandcamp_artist_url: string | null;
    bandcamp_track_url: string | null;
    artist: string | null;
  } | undefined;
  loading: boolean;
  onGoToArtist: (artistName: string) => void;
  onPlayTrack: (item: DiscoveryItem) => void;
  onAddToWishlist: (item: DiscoveryItem) => void;
}) {
  // Transform the discover data to match the hook's expected input
  const trackDiscoveryInput = discoverData ? {
    similarTracks: discoverData.similar_tracks,
    similarArtists: discoverData.similar_artists,
    getArtistImageUrl: () => '', // Not needed for this use case
  } : undefined;

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const { sections, hasDiscovery } = useTrackDiscovery({ data: trackDiscoveryInput as any });

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-zinc-400" />
      </div>
    );
  }

  if (!hasDiscovery) {
    return (
      <div className="h-full overflow-y-auto p-6 pb-32">
        <div className="max-w-4xl mx-auto">
          <div className="text-center text-zinc-500 py-12">
            <Music className="w-12 h-12 mx-auto mb-4 opacity-50" />
            <p>No discovery data available for this track yet.</p>
            <p className="text-sm mt-2">
              Try playing a track that has been analyzed with audio embeddings.
            </p>
          </div>
        </div>
      </div>
    );
  }

  const handleItemClick = (item: DiscoveryItem) => {
    if (item.entityType === 'artist' && item.inLibrary) {
      onGoToArtist(item.name);
    }
  };

  const handleItemPlay = (item: DiscoveryItem) => {
    if (item.entityType === 'track') {
      onPlayTrack(item);
    }
  };

  return (
    <div className="h-full overflow-y-auto p-6 pb-32">
      <div className="max-w-4xl mx-auto space-y-6">
        <DiscoveryPanel
          sections={sections}
          onItemClick={handleItemClick}
          onItemPlay={handleItemPlay}
          onAddToWishlist={onAddToWishlist}
        />

        {/* External Links for Current Track */}
        {(discoverData?.bandcamp_artist_url || discoverData?.bandcamp_track_url) && (
          <section className="pt-4 border-t border-zinc-800">
            <h3 className="text-sm font-medium text-zinc-400 mb-3">Find on Bandcamp</h3>
            <div className="flex gap-2">
              {discoverData.bandcamp_track_url && (
                <a
                  href={discoverData.bandcamp_track_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="px-3 py-1.5 bg-teal-600/20 text-teal-400 hover:bg-teal-600/30 rounded transition-colors text-sm"
                >
                  Search for this track
                </a>
              )}
              {discoverData.bandcamp_artist_url && (
                <a
                  href={discoverData.bandcamp_artist_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="px-3 py-1.5 bg-teal-600/20 text-teal-400 hover:bg-teal-600/30 rounded transition-colors text-sm"
                >
                  More by {discoverData.artist}
                </a>
              )}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

function formatTime(seconds: number): string {
  if (!seconds || !isFinite(seconds)) return '0:00';
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

interface FullPlayerProps {
  onClose: () => void;
}

export function FullPlayer({ onClose }: FullPlayerProps) {
  const [viewMode, setViewMode] = useState<ViewMode>('visualizer');
  const [imageError, setImageError] = useState(false);
  const [lyrics, setLyrics] = useState<LyricLine[] | null>(null);
  const [contextMenu, setContextMenu] = useState<ContextMenuState>(initialContextMenuState);
  const { navigateToArtist, navigateToAlbum } = useAppNavigation();

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
    repeat,
    toggleShuffle,
    toggleRepeat,
  } = usePlayerStore();

  const { seek, togglePlayPause } = useAudioEngine();
  const { addToQueue, setQueue } = usePlayerStore();
  const { isFavorite, toggle: toggleFavorite } = useFavorites();

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

  // Fetch discovery data for the current track
  const { data: discoverData, isLoading: discoverLoading } = useQuery({
    queryKey: ['track-discover', currentTrack?.id],
    queryFn: () => tracksApi.getDiscover(currentTrack!.id, 6, 8),
    staleTime: 5 * 60 * 1000,
    enabled: !!currentTrack?.id,
  });

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
    <div className="fixed inset-0 z-50 bg-black flex flex-col">
      {/* Header - includes safe area padding for notch */}
      <div className="absolute top-0 left-0 right-0 z-10 flex items-center justify-between p-4 pt-safe bg-gradient-to-b from-black/80 to-transparent">
        <button
          onClick={onClose}
          className="p-2 hover:bg-white/10 rounded-full transition-colors"
          aria-label="Close player"
        >
          <X className="w-6 h-6" />
        </button>

        {/* Center: View mode toggle + visualizer picker */}
        <div className="flex items-center gap-3">
          {/* View mode toggle */}
          <div className="flex gap-1 bg-white/10 rounded-lg p-1">
            <button
              onClick={() => setViewMode('visualizer')}
              className={`p-2 rounded-md transition-colors ${
                viewMode === 'visualizer'
                  ? 'bg-white/20 text-white'
                  : 'text-zinc-400 hover:text-white'
              }`}
              title="Visualizer"
            >
              <Music className="w-5 h-5" />
            </button>
            <button
              onClick={() => setViewMode('video')}
              className={`p-2 rounded-md transition-colors ${
                viewMode === 'video'
                  ? 'bg-white/20 text-white'
                  : 'text-zinc-400 hover:text-white'
              }`}
              title="Music Video"
            >
              <Video className="w-5 h-5" />
            </button>
            <button
              onClick={() => setViewMode('lyrics')}
              className={`p-2 rounded-md transition-colors ${
                viewMode === 'lyrics'
                  ? 'bg-white/20 text-white'
                  : 'text-zinc-400 hover:text-white'
              }`}
              title="Lyrics"
            >
              <Type className="w-5 h-5" />
            </button>
            <button
              onClick={() => setViewMode('discover')}
              className={`p-2 rounded-md transition-colors ${
                viewMode === 'discover'
                  ? 'bg-white/20 text-white'
                  : 'text-zinc-400 hover:text-white'
              }`}
              title="Discover Similar"
            >
              <Compass className="w-5 h-5" />
            </button>
          </div>

          {/* Visualizer picker - only show in visualizer mode */}
          {viewMode === 'visualizer' && <VisualizerPicker />}

          {/* Effects quick access */}
          <EffectsQuickAccess />
        </div>

        <div className="w-10" /> {/* Spacer for balance */}
      </div>

      {/* Main content area */}
      <div className="flex-1 relative overflow-hidden">
        {viewMode === 'visualizer' && (
          <AudioVisualizer
            track={currentTrack}
            artworkUrl={artworkUrl}
            lyrics={lyrics}
            currentTime={currentTime}
            className="absolute inset-0"
          />
        )}

        {viewMode === 'video' && (
          <VideoPlayer trackId={currentTrack.id} />
        )}

        {viewMode === 'lyrics' && (
          <LyricsDisplay trackId={currentTrack.id} />
        )}

        {viewMode === 'discover' && (
          <FullPlayerDiscoverTab
            discoverData={discoverData}
            loading={discoverLoading}
            onGoToArtist={(artistName) => {
              navigateToArtist(artistName);
              onClose();
            }}
            onPlayTrack={(item) => {
              if (item.id) {
                if (currentTrack?.id === item.id) {
                  togglePlayPause();
                  return;
                }
                // Find the track in similar_tracks to get all tracks for the queue
                const trackIndex = discoverData?.similar_tracks.findIndex(t => t.id === item.id) ?? -1;
                if (trackIndex !== -1 && discoverData) {
                  setQueue(discoverData.similar_tracks as Track[], trackIndex);
                }
              }
            }}
            onAddToWishlist={async (item) => {
              if (!item.inLibrary && item.name) {
                try {
                  await playlistsApi.addToWishlist({
                    title: item.name,
                    artist: item.subtitle || 'Unknown Artist',
                    album: item.playbackContext?.album,
                  });
                } catch (err) {
                  console.error('Failed to add to wishlist:', err);
                }
              }
            }}
          />
        )}

        {/* Album art overlay (bottom left) */}
        <div className="absolute bottom-32 left-8 z-10">
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
      </div>

      {/* Bottom controls - includes safe area padding for home indicator */}
      <div className="absolute bottom-0 left-0 right-0 z-10 bg-gradient-to-t from-black via-black/95 to-transparent p-4 pt-8 sm:p-6 sm:pt-16 pb-safe">
        {/* Track info - right-click for context menu */}
        <div
          className="text-center mb-6 cursor-context-menu"
          onContextMenu={handleContextMenu}
        >
          <h2 className="text-xl sm:text-2xl font-bold truncate">{currentTrack.title || 'Unknown'}</h2>
          <p className="text-lg text-zinc-400">{currentTrack.artist || 'Unknown'}</p>
          <p className="text-sm text-zinc-500">{currentTrack.album || ''}</p>
        </div>

        {/* Progress bar */}
        <div className="mb-6">
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
        <div className="flex items-center justify-center gap-6">
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
        </div>

        {/* Volume */}
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
            // TODO: Open playlist picker modal
            
          }}
          onMakePlaylist={() => {
            if (contextMenu.track) {
              const track = contextMenu.track;
              const message = `Make me a playlist based on "${track.title || 'this track'}" by ${track.artist || 'Unknown Artist'}`;
              window.dispatchEvent(new CustomEvent('trigger-chat', { detail: { message } }));
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
