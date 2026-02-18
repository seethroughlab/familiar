import { useState, useCallback, useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useParams, useNavigate } from 'react-router-dom';
import { PlayIndicator } from '../common/PlayIndicator';
import {
  ArrowLeft,
  Play,
  Loader2,
  Music,
  Disc,
  Users,
  ExternalLink,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  Heart,
  Download,
  Check,
} from 'lucide-react';
import { libraryApi, tracksApi, playlistsApi } from '../../api/client';
import { AlbumArtwork } from '../AlbumArtwork';
import { usePlayerStore } from '../../stores/playerStore';
import { useSelectionStore } from '../../stores/selectionStore';
import { useFavorites } from '../../hooks/useFavorites';
import { useOfflineTrack } from '../../hooks/useOfflineTrack';
import { useAppNavigation } from '../../hooks/useAppNavigation';
import { TrackContextMenu } from './TrackContextMenu';
import { AlbumContextMenu } from './AlbumContextMenu';
import type { ContextMenuState, AlbumContextMenuState } from './types';
import { initialContextMenuState, initialAlbumContextMenuState } from './types';
import { useDownloadStore, getAlbumJobId } from '../../stores/downloadStore';
import { getOfflineTrackIds, removeOfflineTrack } from '../../services/offlineService';
import type { Track } from '../../types';
import { DiscoveryPanel, useArtistDiscovery, type DiscoveryItem } from '../Discovery';

import { createLogger } from '../../utils/logger';

const log = createLogger('ArtistDetail');

function OfflineButton({ trackId }: { trackId: string }) {
  const { isOffline, isDownloading, downloadProgress, download, remove } = useOfflineTrack(trackId);

  if (isDownloading) {
    return (
      <div
        className="relative p-1 text-purple-400"
        title={`Downloading... ${downloadProgress}%`}
      >
        <Loader2 className="w-4 h-4 animate-spin" />
        {downloadProgress > 0 && downloadProgress < 100 && (
          <span className="absolute -bottom-1 left-1/2 -translate-x-1/2 text-[8px] font-medium">
            {downloadProgress}%
          </span>
        )}
      </div>
    );
  }

  if (isOffline) {
    return (
      <button
        onClick={(e) => {
          e.stopPropagation();
          remove();
        }}
        className="p-1 text-green-500 hover:text-red-400 transition-colors"
        title="Remove offline copy"
      >
        <Check className="w-4 h-4" />
      </button>
    );
  }

  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        download();
      }}
      className="p-1 text-zinc-500 hover:text-white transition-colors opacity-100 sm:opacity-0 sm:group-hover:opacity-100"
      title="Download for offline"
    >
      <Download className="w-4 h-4" />
    </button>
  );
}

function FavoriteButton({ trackId }: { trackId: string }) {
  const { isFavorite, toggle } = useFavorites();
  const favorited = isFavorite(trackId);

  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        toggle(trackId);
      }}
      className={`p-1 transition-colors ${
        favorited
          ? 'text-pink-500 hover:text-pink-400'
          : 'text-zinc-500 hover:text-pink-400 opacity-100 sm:opacity-0 sm:group-hover:opacity-100'
      }`}
      title={favorited ? 'Remove from favorites' : 'Add to favorites'}
    >
      <Heart className="w-4 h-4" fill={favorited ? 'currentColor' : 'none'} />
    </button>
  );
}

// Artist Discovery Section using unified components
function ArtistDiscoverySection({
  artist,
  onGoToArtist,
}: {
  artist: {
    similar_artists: Array<{
      name: string;
      match_score: number;
      in_library: boolean;
      track_count: number | null;
      image_url: string | null;
      lastfm_url: string | null;
      bandcamp_url: string | null;
    }>;
  };
  onGoToArtist: (artistName: string) => void;
}) {
  const { sections, hasDiscovery } = useArtistDiscovery({ artist });

  if (!hasDiscovery) return null;

  const handleItemClick = (item: DiscoveryItem) => {
    if (item.inLibrary) {
      onGoToArtist(item.name);
    }
  };

  const handleAddToWishlist = async (item: DiscoveryItem) => {
    if (!item.inLibrary && item.name) {
      try {
        // For artists, we add a placeholder track
        await playlistsApi.addToWishlist({
          title: `Tracks by ${item.name}`,
          artist: item.name,
        });
      } catch (err) {
        log.error('Failed to add to wishlist:', err);
      }
    }
  };

  return (
    <DiscoveryPanel
      title="Discover More"
      sections={sections}
      collapsible
      onItemClick={handleItemClick}
      onAddToWishlist={handleAddToWishlist}
    />
  );
}

interface Props {
  artistName?: string;
  onBack?: () => void;
  onGoToAlbum?: (artistName: string, albumName: string) => void;
  onGoToGenre?: (genre: string) => void;
  onGoToYear?: (year: number) => void;
}

// Threshold for using lazy queue mode vs loading all tracks
const LAZY_QUEUE_THRESHOLD = 50;
// Number of tracks to show before collapsing
const COLLAPSED_TRACK_COUNT = 15;

export function ArtistDetail({ artistName: artistNameProp, onBack: onBackProp, onGoToAlbum, onGoToGenre, onGoToYear }: Props) {
  // Support both route params and props
  const routeParams = useParams<{ name: string }>();
  const routeNavigate = useNavigate();
  const artistName = artistNameProp || (routeParams.name ? decodeURIComponent(routeParams.name) : '');
  const onBack = onBackProp || (() => routeNavigate(-1));
  const currentTrack = usePlayerStore((s) => s.currentTrack);
  const isPlaying = usePlayerStore((s) => s.isPlaying);
  const shuffle = usePlayerStore((s) => s.shuffle);
  const setQueue = usePlayerStore((s) => s.setQueue);
  const addToQueue = usePlayerStore((s) => s.addToQueue);
  const setIsPlaying = usePlayerStore((s) => s.setIsPlaying);
  const setLazyQueue = usePlayerStore((s) => s.setLazyQueue);
  const { startDownload } = useDownloadStore();
  const { navigateToArtist, navigateToAlbum } = useAppNavigation();
  const [showFullBio, setShowFullBio] = useState(false);
  const [showAllTracks, setShowAllTracks] = useState(false);
  const [contextMenu, setContextMenu] = useState<ContextMenuState>(initialContextMenuState);
  const [albumContextMenu, setAlbumContextMenu] = useState<AlbumContextMenuState>(initialAlbumContextMenuState);
  const [offlineTrackIds, setOfflineTrackIds] = useState<Set<string>>(new Set());
  const [selectedTrackIds, setSelectedTrackIds] = useState<Set<string>>(new Set());
  const [lastClickedId, setLastClickedId] = useState<string | null>(null);

  // Track which artists we've already triggered enrichment for
  const enrichedArtistsRef = useRef<Set<string>>(new Set());

  // Load offline track IDs on mount
  useEffect(() => {
    getOfflineTrackIds().then((ids) => setOfflineTrackIds(new Set(ids)));
  }, []);

  // Context menu handlers
  const handleContextMenu = useCallback((track: Track, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setContextMenu({
      isOpen: true,
      track,
      position: { x: e.clientX, y: e.clientY },
    });
  }, []);

  const closeContextMenu = useCallback(() => {
    setContextMenu(initialContextMenuState);
  }, []);

  // Album context menu handlers
  const handleAlbumContextMenu = useCallback(
    (
      album: { name: string; year: number | null; track_count: number; first_track_id: string },
      e: React.MouseEvent
    ) => {
      e.preventDefault();
      e.stopPropagation();
      setAlbumContextMenu({
        isOpen: true,
        album: {
          name: album.name,
          artist: artistName,
          year: album.year,
          first_track_id: album.first_track_id,
        },
        position: { x: e.clientX, y: e.clientY },
      });
    },
    [artistName]
  );

  const closeAlbumContextMenu = useCallback(() => {
    setAlbumContextMenu(initialAlbumContextMenuState);
  }, []);

  const {
    data: artist,
    isLoading,
    refetch,
    isRefetching,
  } = useQuery({
    queryKey: ['artist', artistName],
    queryFn: () => libraryApi.getArtist(artistName),
  });

  // Auto-enrich all tracks when artist detail loads
  useEffect(() => {
    if (!artist || enrichedArtistsRef.current.has(artistName)) return;
    enrichedArtistsRef.current.add(artistName);

    // Fire-and-forget enrichment for all tracks
    for (const track of artist.tracks) {
      tracksApi.enrich(track.id).catch(() => {
        // Ignore errors - enrichment is best-effort
      });
    }
    // Note: Artwork is now handled reactively by AlbumArtwork components
  }, [artist, artistName]);

  const handleRefreshLastfm = async () => {
    await libraryApi.getArtist(artistName, true);
    refetch();
  };

  const handlePlayAll = async () => {
    if (!artist || artist.tracks.length === 0) return;

    // Use lazy queue mode for large artist catalogs
    // Pass global shuffle state to server for pre-shuffled IDs
    if (artist.tracks.length >= LAZY_QUEUE_THRESHOLD) {
      try {
        const response = await tracksApi.getIds({
          artist: artist.name,
          shuffle: shuffle,
        });
        if (response.ids.length > 0) {
          await setLazyQueue(response.ids);
        }
      } catch (error) {
        log.error('Failed to get track IDs for artist:', error);
      }
      return;
    }

    // For smaller catalogs, use regular queue
    // setQueue() already respects the global shuffle toggle
    const queueTracks = artist.tracks.map((t) => ({
      id: t.id,
      file_path: '',
      title: t.title || 'Unknown',
      artist: artist.name,
      album: t.album || null,
      album_artist: null,
      album_type: 'album' as const,
      track_number: t.track_number,
      disc_number: null,
      year: t.year,
      genre: null,
      duration_seconds: t.duration_seconds || null,
      format: null,
      analysis_version: 0,
    }));
    setQueue(queueTracks, 0);
  };

  const handlePlayAlbum = (albumName: string) => {
    if (!artist) return;

    const albumTracks = artist.tracks.filter((t) => t.album === albumName);
    if (albumTracks.length === 0) return;

    const queueTracks = albumTracks.map((t) => ({
      id: t.id,
      file_path: '',
      title: t.title || 'Unknown',
      artist: artist.name,
      album: t.album || null,
      album_artist: null,
      album_type: 'album' as const,
      track_number: t.track_number,
      disc_number: null,
      year: t.year,
      genre: null,
      duration_seconds: t.duration_seconds || null,
      format: null,
      analysis_version: 0,
    }));
    setQueue(queueTracks, 0);
  };

  const handlePlayTrack = (trackIndex: number) => {
    if (!artist || artist.tracks.length === 0) return;

    // If clicking on the currently playing track, toggle play/pause
    const clickedTrack = artist.tracks[trackIndex];
    if (clickedTrack && currentTrack?.id === clickedTrack.id) {
      setIsPlaying(!isPlaying);
      return;
    }

    const queueTracks = artist.tracks.map((t) => ({
      id: t.id,
      file_path: '',
      title: t.title || 'Unknown',
      artist: artist.name,
      album: t.album || null,
      album_artist: null,
      album_type: 'album' as const,
      track_number: t.track_number,
      disc_number: null,
      year: t.year,
      genre: null,
      duration_seconds: t.duration_seconds || null,
      format: null,
      analysis_version: 0,
    }));
    setQueue(queueTracks, trackIndex);
  };

  const handleTrackClick = useCallback((trackId: string, idx: number, e: React.MouseEvent) => {
    if (!artist) return;

    if (e.shiftKey && lastClickedId) {
      // Shift-click: select range
      const lastIdx = artist.tracks.findIndex(t => t.id === lastClickedId);
      const [start, end] = [Math.min(lastIdx, idx), Math.max(lastIdx, idx)];
      const rangeIds = artist.tracks.slice(start, end + 1).map(t => t.id);
      setSelectedTrackIds(new Set([...selectedTrackIds, ...rangeIds]));
    } else if (e.metaKey || e.ctrlKey) {
      // Cmd/Ctrl-click: toggle single selection
      const newSet = new Set(selectedTrackIds);
      if (newSet.has(trackId)) newSet.delete(trackId);
      else newSet.add(trackId);
      setSelectedTrackIds(newSet);
    } else {
      // Plain click: select only this track
      setSelectedTrackIds(new Set([trackId]));
    }
    setLastClickedId(trackId);
  }, [artist, lastClickedId, selectedTrackIds]);

  const formatDuration = (seconds: number | null) => {
    if (!seconds) return '--:--';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const formatNumber = (num: number | null) => {
    if (!num) return '0';
    return num.toLocaleString();
  };

  // Strip HTML from Last.fm bio
  const stripHtml = (html: string | null) => {
    if (!html) return '';
    return html
      .replace(/<[^>]*>/g, '')
      .replace(/&quot;/g, '"')
      .replace(/&amp;/g, '&')
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&#\d+;/g, '');
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-6 h-6 animate-spin text-zinc-400" />
      </div>
    );
  }

  if (!artist) {
    return (
      <div className="text-center py-12 text-zinc-500">
        <p>Artist not found</p>
        <button
          onClick={onBack}
          className="mt-4 text-green-500 hover:text-green-400"
        >
          Go back
        </button>
      </div>
    );
  }

  const bioText = stripHtml(showFullBio ? artist.bio_content : artist.bio_summary);

  return (
    <div className="space-y-6 pb-6 px-4 md:px-0">
      {/* Header - stacks vertically on mobile */}
      <div className="space-y-4">
        {/* Back button row */}
        <button
          onClick={onBack}
          className="p-2 hover:bg-zinc-800 rounded-lg transition-colors -ml-2"
        >
          <ArrowLeft className="w-5 h-5" />
        </button>

        {/* Artist info row - horizontal on desktop, adapts on mobile */}
        <div className="flex flex-col sm:flex-row gap-4">
          {/* Artist image or fallback */}
          <div className="w-24 h-24 sm:w-32 sm:h-32 rounded-lg bg-zinc-800 overflow-hidden flex-shrink-0 relative mx-auto sm:mx-0">
            {artist.image_url ? (
              <img
                src={artist.image_url}
                alt={artist.name}
                className="w-full h-full object-cover"
                onError={(e) => {
                  e.currentTarget.style.display = 'none';
                }}
              />
            ) : (
              <img
                src={tracksApi.getArtworkUrl(artist.first_track_id, 'thumb')}
                alt={artist.name}
                className="w-full h-full object-cover"
                onError={(e) => {
                  e.currentTarget.style.display = 'none';
                }}
              />
            )}
            {/* Fallback icon if both images fail */}
            <div className="absolute inset-0 flex items-center justify-center -z-10">
              <Users className="w-12 h-12 text-zinc-600" />
            </div>
          </div>

          <div className="flex-1 min-w-0 text-center sm:text-left">
            <h2 className="text-xl sm:text-2xl font-bold truncate">{artist.name}</h2>

            {/* Stats row - wraps on mobile */}
            <div className="flex flex-wrap items-center justify-center sm:justify-start gap-x-4 gap-y-1 mt-2 text-sm text-zinc-400">
              <span className="flex items-center gap-1">
                <Music className="w-4 h-4" />
                {artist.track_count} tracks
              </span>
              <span className="flex items-center gap-1">
                <Disc className="w-4 h-4" />
                {artist.album_count} albums
              </span>
            </div>

            {/* Last.fm stats */}
            {artist.listeners && (
              <div className="flex flex-wrap items-center justify-center sm:justify-start gap-x-3 gap-y-1 mt-1 text-xs text-zinc-500">
                <span>{formatNumber(artist.listeners)} listeners</span>
                {artist.playcount && (
                  <span>{formatNumber(artist.playcount)} scrobbles</span>
                )}
              </div>
            )}

            {/* Tags */}
            {artist.tags?.length > 0 && (
              <div className="flex flex-wrap justify-center sm:justify-start gap-1 mt-2">
                {artist.tags.slice(0, 5).map((tag) => (
                  <button
                    key={tag}
                    onClick={() => onGoToGenre?.(tag)}
                    className="px-2 py-0.5 text-xs bg-zinc-800 text-zinc-400 hover:text-white hover:bg-zinc-700 rounded transition-colors"
                  >
                    {tag}
                  </button>
                ))}
              </div>
            )}

            {/* Actions - inline on larger screens */}
            <div className="hidden sm:flex items-center gap-2 mt-3">
              <button
                onClick={handlePlayAll}
                disabled={!artist.tracks?.length}
                className="flex items-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-500 disabled:opacity-50 rounded-full transition-colors"
              >
                <Play className="w-4 h-4" fill="currentColor" />
                Play
              </button>

              {artist.lastfm_url && (
                <a
                  href={artist.lastfm_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="p-2 hover:bg-zinc-800 rounded-lg transition-colors"
                  title="View on Last.fm"
                >
                  <ExternalLink className="w-5 h-5 text-zinc-400" />
                </a>
              )}

              <button
                onClick={handleRefreshLastfm}
                disabled={isRefetching}
                className="p-2 hover:bg-zinc-800 rounded-lg transition-colors"
                title="Refresh Last.fm data"
              >
                <RefreshCw
                  className={`w-5 h-5 text-zinc-400 ${isRefetching ? 'animate-spin' : ''}`}
                />
              </button>
            </div>
          </div>
        </div>

        {/* Mobile-only actions row */}
        <div className="flex sm:hidden items-center justify-center gap-3">
          <button
            onClick={handlePlayAll}
            disabled={!artist.tracks?.length}
            className="flex items-center gap-2 px-6 py-2.5 bg-green-600 hover:bg-green-500 disabled:opacity-50 rounded-full transition-colors"
          >
            <Play className="w-5 h-5" fill="currentColor" />
            Play All
          </button>

          {artist.lastfm_url && (
            <a
              href={artist.lastfm_url}
              target="_blank"
              rel="noopener noreferrer"
              className="p-2.5 bg-zinc-800 hover:bg-zinc-700 rounded-full transition-colors"
              title="View on Last.fm"
            >
              <ExternalLink className="w-5 h-5 text-zinc-400" />
            </a>
          )}

          <button
            onClick={handleRefreshLastfm}
            disabled={isRefetching}
            className="p-2.5 bg-zinc-800 hover:bg-zinc-700 rounded-full transition-colors"
            title="Refresh Last.fm data"
          >
            <RefreshCw
              className={`w-5 h-5 text-zinc-400 ${isRefetching ? 'animate-spin' : ''}`}
            />
          </button>
        </div>
      </div>

      {/* Bio section */}
      {bioText && (
        <div className="bg-zinc-800/50 rounded-lg p-4">
          <p className="text-sm text-zinc-300 whitespace-pre-wrap">{bioText}</p>
          {artist.bio_content &&
            artist.bio_content !== artist.bio_summary && (
              <button
                onClick={() => setShowFullBio(!showFullBio)}
                className="flex items-center gap-1 mt-2 text-xs text-purple-400 hover:text-purple-300"
              >
                {showFullBio ? (
                  <>
                    <ChevronUp className="w-4 h-4" />
                    Show less
                  </>
                ) : (
                  <>
                    <ChevronDown className="w-4 h-4" />
                    Read more
                  </>
                )}
              </button>
            )}
        </div>
      )}

      {/* Albums section */}
      {artist.albums?.length > 0 && (
        <div>
          <h3 className="text-lg font-semibold mb-3">Albums in Library</h3>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4">
            {artist.albums.map((album) => (
              <div
                key={album.name}
                className="group bg-zinc-800/50 rounded-lg overflow-hidden hover:bg-zinc-800 transition-colors cursor-pointer"
                onClick={() => onGoToAlbum?.(artist.name, album.name)}
                onContextMenu={(e) => handleAlbumContextMenu(album, e)}
              >
                <div className="aspect-square relative overflow-hidden">
                  <AlbumArtwork
                    artist={artist.name}
                    album={album.name}
                    trackId={album.first_track_id}
                    size="thumb"
                    className="w-full h-full"
                  />
                  <button
                    className="absolute inset-0 flex items-center justify-center bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity z-20"
                    onClick={(e) => {
                      e.stopPropagation();
                      handlePlayAlbum(album.name);
                      onGoToAlbum?.(artist.name, album.name);
                    }}
                  >
                    <Play className="w-10 h-10" fill="currentColor" />
                  </button>
                </div>
                <div className="p-3">
                  <div className="font-medium truncate">{album.name}</div>
                  <div className="text-xs text-zinc-400">
                    {album.year && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onGoToYear?.(album.year!);
                        }}
                        className="hover:text-white hover:underline transition-colors"
                      >
                        {album.year}
                      </button>
                    )}
                    {album.year && ' · '}
                    {album.track_count} tracks
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* All tracks section */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-semibold">All Tracks</h3>
          {(artist.tracks?.length ?? 0) > COLLAPSED_TRACK_COUNT && (
            <span className="text-sm text-zinc-400">
              {artist.tracks.length} tracks
            </span>
          )}
        </div>
        <div className="space-y-1">
          {(showAllTracks ? (artist.tracks ?? []) : (artist.tracks ?? []).slice(0, COLLAPSED_TRACK_COUNT)).map((track, idx) => {
            // Convert to full Track type for context menu
            const fullTrack: Track = {
              id: track.id,
              file_path: '',
              title: track.title || null,
              artist: artist.name,
              album: track.album || null,
              album_artist: null,
              album_type: 'album',
              track_number: track.track_number,
              disc_number: null,
              year: track.year,
              genre: null,
              duration_seconds: track.duration_seconds || null,
              format: null,
              analysis_version: 0,
            };
            return (
            <div
              key={track.id}
              draggable
              onDragStart={(e) => {
                e.dataTransfer.setData('application/track-id', track.id);
                e.dataTransfer.effectAllowed = 'copy';
              }}
              onClick={(e) => handleTrackClick(track.id, idx, e)}
              onDoubleClick={() => handlePlayTrack(idx)}
              onMouseDown={(e) => {
                if (e.shiftKey || e.metaKey || e.ctrlKey) e.preventDefault();
              }}
              onContextMenu={(e) => handleContextMenu(fullTrack, e)}
              className={`group flex items-center gap-3 p-2 rounded-lg hover:bg-zinc-800/50 cursor-pointer transition-colors ${
                selectedTrackIds.has(track.id)
                  ? 'bg-purple-500/20 hover:bg-purple-500/30'
                  : currentTrack?.id === track.id
                    ? 'bg-zinc-800/30'
                    : ''
              }`}
            >
              <div className="w-8 text-center cursor-pointer" onClick={(e) => { e.stopPropagation(); handlePlayTrack(idx); }}>
                <PlayIndicator isCurrent={currentTrack?.id === track.id} isPlaying={isPlaying} index={track.track_number || idx + 1} />
              </div>

              <div className="flex-1 min-w-0">
                <div className={`font-medium truncate ${currentTrack?.id === track.id ? 'text-green-500' : ''}`}>
                  {track.title || 'Unknown Title'}
                </div>
                {track.album && (
                  <div className="text-sm text-zinc-500 truncate">
                    {track.album}
                  </div>
                )}
              </div>

              <div className="text-sm text-zinc-500">
                {formatDuration(track.duration_seconds)}
              </div>

              <FavoriteButton trackId={track.id} />
              <OfflineButton trackId={track.id} />
            </div>
            );
          })}
        </div>

        {/* Show all/less toggle */}
        {(artist.tracks?.length ?? 0) > COLLAPSED_TRACK_COUNT && (
          <button
            onClick={() => setShowAllTracks(!showAllTracks)}
            className="flex items-center gap-2 mt-3 px-4 py-2 w-full justify-center text-sm text-zinc-400 hover:text-white hover:bg-zinc-800/50 rounded-lg transition-colors"
          >
            {showAllTracks ? (
              <>
                <ChevronUp className="w-4 h-4" />
                Show less
              </>
            ) : (
              <>
                <ChevronDown className="w-4 h-4" />
                Show all {artist.tracks.length} tracks
              </>
            )}
          </button>
        )}
      </div>

      {/* Similar artists */}
      <ArtistDiscoverySection
        artist={artist}
        onGoToArtist={(name) => navigateToArtist(name)}
      />

      {/* Context menu */}
      {contextMenu.isOpen && contextMenu.track && (
        <TrackContextMenu
          track={contextMenu.track}
          position={contextMenu.position}
          isSelected={selectedTrackIds.has(contextMenu.track.id)}
          selectedCount={selectedTrackIds.size}
          onClose={closeContextMenu}
          onPlay={() => {
            const idx = artist.tracks.findIndex(t => t.id === contextMenu.track?.id);
            if (idx !== -1) handlePlayTrack(idx);
          }}
          onQueue={() => {
            if (contextMenu.track) {
              addToQueue(contextMenu.track);
            }
          }}
          onGoToArtist={() => {
            // Already on this artist's page
          }}
          onGoToAlbum={() => {
            if (contextMenu.track?.album) {
              navigateToAlbum(artistName, contextMenu.track.album);
            }
          }}
          onToggleSelect={() => {
            if (contextMenu.track) {
              const newSet = new Set(selectedTrackIds);
              if (newSet.has(contextMenu.track.id)) {
                newSet.delete(contextMenu.track.id);
              } else {
                newSet.add(contextMenu.track.id);
              }
              setSelectedTrackIds(newSet);
            }
          }}
          onClearSelection={() => setSelectedTrackIds(new Set())}
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
              if (selectedTrackIds.size > 1 && selectedTrackIds.has(contextMenu.track.id)) {
                useSelectionStore.getState().selectAll(Array.from(selectedTrackIds));
              }
              useSelectionStore.getState().setEditingTrackId(contextMenu.track.id);
            }
          }}
        />
      )}

      {/* Album context menu */}
      {albumContextMenu.isOpen && albumContextMenu.album && (
        <AlbumContextMenu
          album={albumContextMenu.album}
          position={albumContextMenu.position}
          onClose={closeAlbumContextMenu}
          onPlay={() => {
            if (albumContextMenu.album && artist) {
              handlePlayAlbum(albumContextMenu.album.name);
            }
          }}
          onShuffle={() => {
            if (albumContextMenu.album && artist) {
              const albumTracks = artist.tracks.filter(
                (t) => t.album === albumContextMenu.album!.name
              );
              if (albumTracks.length === 0) return;

              // Shuffle the tracks before setting queue
              const queueTracks = albumTracks
                .map((t) => ({
                  id: t.id,
                  file_path: '',
                  title: t.title || 'Unknown',
                  artist: artist.name,
                  album: t.album || null,
                  album_artist: null,
                  album_type: 'album' as const,
                  track_number: t.track_number,
                  disc_number: null,
                  year: t.year,
                  genre: null,
                  duration_seconds: t.duration_seconds || null,
                  format: null,
                  analysis_version: 0,
                }))
                .sort(() => Math.random() - 0.5);
              setQueue(queueTracks, 0);
            }
          }}
          onQueue={() => {
            if (albumContextMenu.album && artist) {
              const albumTracks = artist.tracks.filter(
                (t) => t.album === albumContextMenu.album!.name
              );
              for (const t of albumTracks) {
                addToQueue({
                  id: t.id,
                  file_path: '',
                  title: t.title || 'Unknown',
                  artist: artist.name,
                  album: t.album || null,
                  album_artist: null,
                  album_type: 'album',
                  track_number: t.track_number,
                  disc_number: null,
                  year: t.year,
                  genre: null,
                  duration_seconds: t.duration_seconds || null,
                  format: null,
                  analysis_version: 0,
                });
              }
            }
          }}
          onGoToArtist={() => {
            // Already on this artist's page
          }}
          onGoToAlbum={() => {
            if (albumContextMenu.album) {
              onGoToAlbum?.(albumContextMenu.album.artist, albumContextMenu.album.name);
            }
          }}
          onDownload={() => {
            if (albumContextMenu.album && artist) {
              const albumTracks = artist.tracks.filter(
                (t) => t.album === albumContextMenu.album!.name
              );
              const trackIds = albumTracks.map((t) => t.id);
              const jobId = getAlbumJobId(artist.name, albumContextMenu.album.name);
              startDownload(
                jobId,
                'album',
                `${artist.name} - ${albumContextMenu.album.name}`,
                trackIds
              );
            }
          }}
          onRemoveDownload={async () => {
            if (albumContextMenu.album && artist) {
              const albumTracks = artist.tracks.filter(
                (t) => t.album === albumContextMenu.album!.name
              );
              for (const t of albumTracks) {
                if (offlineTrackIds.has(t.id)) {
                  await removeOfflineTrack(t.id);
                }
              }
              // Refresh offline IDs
              const ids = await getOfflineTrackIds();
              setOfflineTrackIds(new Set(ids));
            }
          }}
          hasDownloadedTracks={(() => {
            if (!albumContextMenu.album || !artist) return false;
            const albumTracks = artist.tracks.filter(
              (t) => t.album === albumContextMenu.album!.name
            );
            return albumTracks.some((t) => offlineTrackIds.has(t.id));
          })()}
          onAddToPlaylist={() => {
            // TODO: Open playlist picker modal
          }}
          onMakePlaylist={() => {
            if (albumContextMenu.album) {
              const album = albumContextMenu.album;
              const message = `Make me a playlist based on the album "${album.name}" by ${album.artist}`;
              window.dispatchEvent(new CustomEvent('trigger-chat', { detail: { message } }));
            }
          }}
        />
      )}
    </div>
  );
}
