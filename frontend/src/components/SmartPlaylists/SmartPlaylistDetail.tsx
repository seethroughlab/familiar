import { useState, useEffect, useCallback, useMemo } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Play, Loader2, Music, Zap, Clock, Download, Check, Heart, RefreshCw, CloudOff, Search, X, RotateCw } from 'lucide-react';
import { smartPlaylistsApi, tracksApi, playlistsApi } from '../../api/client';
import { PlayIndicator } from '../common/PlayIndicator';
import type { SmartPlaylist, SmartPlaylistTracksResponse } from '../../api/client';
import { usePlayerStore } from '../../stores/playerStore';
import { useSelectionStore } from '../../stores/selectionStore';
import { useDownloadStore, getSmartPlaylistJobId } from '../../stores/downloadStore';
import { useFavorites } from '../../hooks/useFavorites';
import { useOfflineStatus } from '../../hooks/useOfflineStatus';
import { useAppNavigation } from '../../hooks/useAppNavigation';
import { useAutoDownload } from '../../hooks/useAutoDownload';
import * as offlineService from '../../services/offlineService';
import * as playlistCache from '../../services/playlistCache';
import { TrackContextMenu } from '../Library/TrackContextMenu';
import type { ContextMenuState } from '../Library/types';
import { initialContextMenuState } from '../Library/types';
import { useColumnStore, getVisibleColumns } from '../../stores/columnStore';
import { getColumnDef } from '../Library/columnDefinitions';
import { useLocalSort, useSortedTracks, buildGridColumns } from '../shared/PlaylistColumns';
import { PlaylistColumnHeader } from '../shared/PlaylistColumnHeader';
import type { Track } from '../../types';
import { DiscoveryPanel, useTrackDiscovery, type DiscoveryItem } from '../Discovery';

import { createLogger } from '../../utils/logger';

const log = createLogger('SmartPlaylistDetail');

// Discovery section component
function SmartPlaylistDiscoverySection({
  sections,
  hasDiscovery,
  loading,
  onGoToArtist,
  onPlayTrack,
}: {
  sections: Array<{
    id: string;
    title: string;
    entityType: 'track' | 'album' | 'artist';
    items: DiscoveryItem[];
    layout?: 'list' | 'grid';
  }>;
  hasDiscovery: boolean;
  loading: boolean;
  onGoToArtist: (artistName: string) => void;
  onPlayTrack: (item: DiscoveryItem) => void;
}) {
  if (loading) {
    return (
      <div className="mt-6 border-t border-zinc-800 pt-4">
        <DiscoveryPanel sections={[]} loading={true} />
      </div>
    );
  }

  if (!hasDiscovery) return null;

  const handleItemClick = (item: DiscoveryItem) => {
    if (item.entityType === 'artist' && item.inLibrary) {
      onGoToArtist(item.name);
    }
  };

  const handleAddToWishlist = async (item: DiscoveryItem) => {
    if (!item.inLibrary && item.name) {
      try {
        if (item.entityType === 'artist') {
          // For artists, add a placeholder track
          await playlistsApi.addToWishlist({
            title: `Tracks by ${item.name}`,
            artist: item.name,
          });
        } else {
          await playlistsApi.addToWishlist({
            title: item.name,
            artist: item.subtitle || 'Unknown Artist',
            album: item.playbackContext?.album,
          });
        }
      } catch (err) {
        log.error('Failed to add to wishlist:', err);
      }
    }
  };

  return (
    <div className="mt-6 border-t border-zinc-800 pt-4">
      <DiscoveryPanel
        title="Discover More"
        sections={sections}
        collapsible
        defaultExpanded
        onItemClick={handleItemClick}
        onItemPlay={onPlayTrack}
        onAddToWishlist={handleAddToWishlist}
      />
    </div>
  );
}

interface Props {
  playlist?: SmartPlaylist;
  onBack?: () => void;
}

export function SmartPlaylistDetail({ playlist: playlistProp, onBack: onBackProp }: Props) {
  const routeParams = useParams<{ id: string }>();
  const routeNavigate = useNavigate();
  const onBack = onBackProp || (() => routeNavigate(-1));
  const queryClient = useQueryClient();

  // Fetch playlist from route param if not provided as prop
  const { data: fetchedPlaylist } = useQuery({
    queryKey: ['smart-playlist', routeParams.id],
    queryFn: () => smartPlaylistsApi.get(routeParams.id!),
    enabled: !playlistProp && !!routeParams.id,
  });

  const playlist = playlistProp || fetchedPlaylist;

  if (!playlist) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-6 h-6 animate-spin text-zinc-400" />
      </div>
    );
  }
  const currentTrack = usePlayerStore((s) => s.currentTrack);
  const isPlaying = usePlayerStore((s) => s.isPlaying);
  const setQueue = usePlayerStore((s) => s.setQueue);
  const addToQueue = usePlayerStore((s) => s.addToQueue);
  const setIsPlaying = usePlayerStore((s) => s.setIsPlaying);
  const { isFavorite, toggle: toggleFavorite } = useFavorites();
  const { isOffline } = useOfflineStatus();
  const { navigateToArtist, navigateToAlbum } = useAppNavigation();
  const [offlineTrackIds, setOfflineTrackIds] = useState<Set<string>>(new Set());
  const [contextMenu, setContextMenu] = useState<ContextMenuState>(initialContextMenuState);
  const [usingCachedData, setUsingCachedData] = useState(false);
  const [showDownloadedOnly, setShowDownloadedOnly] = useState(false);
  const [searchFilter, setSearchFilter] = useState('');

  // Column + sort state
  const columns = useColumnStore((s) => s.columns);
  const { sortBy, sortOrder, toggleSort } = useLocalSort();
  const visibleColumnIds = useMemo(() => getVisibleColumns(columns), [columns]);
  const gridColumns = useMemo(
    () => buildGridColumns(columns, ['3rem', '4.5rem']),
    [columns],
  );
  const getTrackFromItem = useCallback(
    (t: SmartPlaylistTracksResponse['tracks'][0]): Track => ({
      id: t.id,
      file_path: t.file_path ?? '',
      title: t.title,
      artist: t.artist,
      album: t.album,
      album_artist: t.album_artist ?? null,
      album_type: (t.album_type as Track['album_type']) ?? 'album',
      track_number: t.track_number ?? null,
      disc_number: t.disc_number ?? null,
      year: t.year ?? null,
      genre: t.genre ?? null,
      duration_seconds: t.duration_seconds,
      format: t.format ?? null,
      analysis_version: t.analysis_version ?? 0,
    }),
    [],
  );

  // Use global download store
  const { jobs, startDownload } = useDownloadStore();
  const jobId = getSmartPlaylistJobId(playlist.id);
  const downloadJob = jobs.get(jobId);
  const isDownloading = downloadJob?.status === 'downloading' || downloadJob?.status === 'queued';
  const downloadProgress = {
    current: downloadJob ? downloadJob.completedIds.length + (downloadJob.currentProgress > 0 ? 1 : 0) : 0,
    total: downloadJob?.trackIds.length ?? 0,
  };

  // Fetch tracks for this smart playlist with offline fallback
  const { data: tracksResponse, isLoading: tracksLoading, refetch } = useQuery({
    queryKey: ['smart-playlist-tracks', playlist.id],
    queryFn: async () => {
      try {
        const result = await smartPlaylistsApi.getTracks(playlist.id, 500);
        setUsingCachedData(false);

        // Cache the smart playlist with its track IDs
        await playlistCache.cacheSmartPlaylist(
          playlist,
          result.tracks.map((t) => t.id)
        );

        return result;
      } catch (error) {
        // If offline, try to load from cache
        if (isOffline) {
          const cached = await playlistCache.getCachedSmartPlaylist(playlist.id);
          if (cached) {
            // Resolve track metadata from cached tracks
            const resolvedTracks = await playlistCache.resolveTrackIds(cached.track_ids);
            setUsingCachedData(true);
            return {
              playlist: {
                ...playlist,
                cached_track_count: cached.cached_track_count,
              },
              tracks: resolvedTracks.map((t) => ({
                id: t.id,
                file_path: '',
                title: t.title,
                artist: t.artist,
                album: t.album,
                album_artist: null,
                album_type: 'album' as const,
                track_number: null,
                disc_number: null,
                duration_seconds: t.durationSeconds,
                genre: t.genre,
                year: t.year,
                format: null,
                analysis_version: 0,
              })),
              total: resolvedTracks.length,
            };
          }
        }
        throw error;
      }
    },
    retry: isOffline ? false : 3,
  });

  const allTracks = tracksResponse?.tracks || [];

  // Filter by downloaded tracks and search query
  const filteredTracks = useMemo(() => {
    let result = allTracks;
    if (showDownloadedOnly) {
      result = result.filter(t => offlineTrackIds.has(t.id));
    }
    if (searchFilter) {
      const q = searchFilter.toLowerCase();
      result = result.filter(t =>
        (t.title?.toLowerCase().includes(q)) ||
        (t.artist?.toLowerCase().includes(q)) ||
        (t.album?.toLowerCase().includes(q))
      );
    }
    return result;
  }, [allTracks, showDownloadedOnly, offlineTrackIds, searchFilter]);

  const tracks = useSortedTracks(filteredTracks, sortBy, sortOrder, getTrackFromItem);

  // Fetch discovery data based on the first track in the playlist (not available offline)
  const firstTrackId = tracks[0]?.id;
  const { data: discoverData, isLoading: discoverLoading } = useQuery({
    queryKey: ['track-discover', firstTrackId],
    queryFn: () => tracksApi.getDiscover(firstTrackId!, 6, 8),
    staleTime: 5 * 60 * 1000,
    enabled: !!firstTrackId && !isOffline && !usingCachedData,
  });

  // Transform discovery data
  const { sections: discoverySections, hasDiscovery } = useTrackDiscovery({
    data: discoverData ? {
      similar_tracks: discoverData.similar_tracks,
      similar_artists: discoverData.similar_artists,
    } : undefined,
  });

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

  // Check which tracks are already offline
  useEffect(() => {
    const checkOfflineStatus = async () => {
      const ids = await offlineService.getOfflineTrackIds();
      setOfflineTrackIds(new Set(ids));
    };
    checkOfflineStatus();
  }, []);

  const handleDownloadPlaylist = async () => {
    if (allTracks.length === 0) return;

    // Get tracks that need to be downloaded (use allTracks, not filtered tracks)
    const tracksToDownload = allTracks.filter(
      (t) => !offlineTrackIds.has(t.id)
    );
    if (tracksToDownload.length === 0) return;

    // Start download via global store
    startDownload(
      jobId,
      'smart-playlist',
      playlist.name,
      tracksToDownload.map((t) => t.id)
    );

    // Cache the smart playlist metadata for offline access
    await playlistCache.cacheSmartPlaylist(
      playlist,
      allTracks.map((t) => t.id)
    );
  };

  // Update offline track IDs when download job completes
  useEffect(() => {
    if (downloadJob?.status === 'completed' || downloadJob?.status === 'failed') {
      // Refresh offline IDs after download completes
      offlineService.getOfflineTrackIds().then((ids) => {
        setOfflineTrackIds(new Set(ids));
      });
    }
  }, [downloadJob?.status]);

  const allTracksOffline = allTracks.every(t => offlineTrackIds.has(t.id));
  const offlineCount = allTracks.filter(t => offlineTrackIds.has(t.id)).length;
  const allTrackIds = useMemo(() => allTracks.map(t => t.id), [allTracks]);

  // Auto-download new tracks when enabled
  useAutoDownload({
    enabled: playlist.auto_download,
    jobId,
    jobType: 'smart-playlist',
    jobName: playlist.name,
    trackIds: allTrackIds,
  });

  const handlePlay = (startIndex = 0) => {
    if (tracks.length === 0) return;

    // If clicking on the currently playing track, toggle play/pause
    const clickedTrack = tracks[startIndex];
    if (clickedTrack && currentTrack?.id === clickedTrack.id) {
      setIsPlaying(!isPlaying);
      return;
    }

    const queueTracks = tracks.map(t => getTrackFromItem(t));
    setQueue(queueTracks, startIndex);
  };

  const formatDuration = (seconds: number | null) => {
    if (!seconds) return '--:--';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  // Format rule for display
  const formatRule = (rule: { field: string; operator: string; value?: unknown }) => {
    const fieldLabels: Record<string, string> = {
      title: 'Title',
      artist: 'Artist',
      album: 'Album',
      album_artist: 'Album Artist',
      genre: 'Genre',
      year: 'Year',
      track_number: 'Track #',
      duration_seconds: 'Duration',
      format: 'Format',
      created_at: 'Added',
      bpm: 'BPM',
      energy: 'Energy',
      valence: 'Mood',
      danceability: 'Danceability',
    };

    const operatorLabels: Record<string, string> = {
      equals: '=',
      not_equals: '≠',
      contains: 'contains',
      greater_than: '>',
      less_than: '<',
      within_days: 'within last',
    };

    const field = fieldLabels[rule.field] || rule.field;
    const op = operatorLabels[rule.operator] || rule.operator;
    const value = rule.operator === 'within_days' ? `${rule.value} days` : String(rule.value || '');

    return `${field} ${op} ${value}`;
  };

  const totalDuration = tracks.reduce(
    (sum, t) => sum + (t.duration_seconds || 0),
    0
  );

  if (tracksLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-6 h-6 animate-spin text-zinc-400" />
      </div>
    );
  }

  return (
    <div className="space-y-4 p-4">
      {/* Header */}
      <div className="space-y-4">
        {/* Back button row */}
        <button
          onClick={onBack}
          className="p-2 hover:bg-zinc-800 rounded-lg transition-colors -ml-2"
        >
          <ArrowLeft className="w-5 h-5" />
        </button>

        {/* Playlist info */}
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Zap className="w-5 h-5 text-yellow-500 flex-shrink-0" />
            <h2 className="text-xl font-bold truncate">{playlist.name}</h2>
            {usingCachedData && (
              <span className="flex items-center gap-1 px-2 py-0.5 text-xs bg-amber-500/20 text-amber-400 rounded-full">
                <CloudOff className="w-3 h-3" />
                Offline
              </span>
            )}
          </div>

          {playlist.description && (
            <p className="text-sm text-zinc-400 mt-1">{playlist.description}</p>
          )}

          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-2 text-sm text-zinc-500">
            <span>{tracks.length} tracks</span>
            <span className="flex items-center gap-1">
              <Clock className="w-4 h-4" />
              {Math.floor(totalDuration / 60)} min
            </span>
          </div>

          {/* Rules display */}
          <div className="flex flex-wrap gap-2 mt-3">
            {playlist.rules.map((rule, idx) => (
              <span
                key={idx}
                className="px-2 py-1 bg-zinc-800 text-zinc-400 text-xs rounded-full"
              >
                {formatRule(rule)}
              </span>
            ))}
            {playlist.match_mode === 'any' && (
              <span className="px-2 py-1 bg-yellow-500/20 text-yellow-500 text-xs rounded-full">
                Match any
              </span>
            )}
          </div>
        </div>

        {/* Action buttons */}
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
          <button
            onClick={() => handlePlay()}
            disabled={tracks.length === 0}
            className="flex items-center justify-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-500 disabled:opacity-50 disabled:hover:bg-green-600 rounded-full transition-colors"
          >
            <Play className="w-4 h-4" fill="currentColor" />
            Play
          </button>

          <button
            onClick={() => refetch()}
            disabled={isOffline}
            className="flex items-center justify-center gap-2 px-4 py-2 bg-zinc-700 hover:bg-zinc-600 disabled:opacity-50 disabled:hover:bg-zinc-700 rounded-full transition-colors"
            title={isOffline ? 'Cannot refresh while offline' : 'Refresh tracks'}
          >
            <RefreshCw className="w-4 h-4" />
            Refresh
          </button>

          <button
            onClick={handleDownloadPlaylist}
            disabled={allTracks.length === 0 || isDownloading || allTracksOffline || isOffline}
            className="flex items-center justify-center gap-2 px-4 py-2 bg-zinc-700 hover:bg-zinc-600 disabled:opacity-50 disabled:hover:bg-zinc-700 rounded-full transition-colors"
            title={isOffline ? 'Cannot download while offline' : allTracksOffline ? 'All tracks downloaded' : 'Download for offline'}
          >
            {isDownloading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                <span className="text-sm">
                  {downloadProgress.current}/{downloadProgress.total}
                </span>
              </>
            ) : allTracksOffline ? (
              <>
                <Check className="w-4 h-4 text-green-400" />
                <span>Offline</span>
              </>
            ) : (
              <>
                <Download className="w-4 h-4" />
                <span>
                  {offlineCount > 0 ? `${offlineCount}/${allTracks.length}` : 'Download'}
                </span>
              </>
            )}
          </button>

          {/* Auto-download toggle */}
          <button
            onClick={async () => {
              const newValue = !playlist.auto_download;
              await smartPlaylistsApi.update(playlist.id, { auto_download: newValue });
              queryClient.setQueryData<SmartPlaylist[]>(['smart-playlists'], (old) =>
                old?.map((p) => (p.id === playlist.id ? { ...p, auto_download: newValue } : p))
              );
            }}
            className={`flex items-center justify-center gap-2 px-4 py-2 rounded-full transition-colors ${
              playlist.auto_download
                ? 'bg-blue-600 hover:bg-blue-500'
                : 'bg-zinc-700 hover:bg-zinc-600'
            }`}
            title={playlist.auto_download ? 'Disable auto-download' : 'Auto-download new tracks'}
          >
            <RotateCw className="w-4 h-4" />
            <span className="text-sm">Auto</span>
          </button>

          {/* Downloaded only filter toggle */}
          {offlineCount > 0 && (
            <button
              onClick={() => setShowDownloadedOnly(!showDownloadedOnly)}
              className={`flex items-center justify-center gap-2 px-4 py-2 rounded-full transition-colors ${
                showDownloadedOnly
                  ? 'bg-green-600 hover:bg-green-500'
                  : 'bg-zinc-700 hover:bg-zinc-600'
              }`}
              title={showDownloadedOnly ? 'Show all tracks' : 'Show only downloaded tracks'}
            >
              <Download className="w-4 h-4" />
              <span className="text-sm">
                {showDownloadedOnly ? `Downloaded (${offlineCount})` : 'Downloaded only'}
              </span>
            </button>
          )}
        </div>
      </div>

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
        <input
          type="text"
          value={searchFilter}
          onChange={(e) => setSearchFilter(e.target.value)}
          placeholder="Search tracks..."
          className="w-full pl-9 pr-8 py-2 bg-zinc-800 rounded-lg text-sm placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-zinc-600"
        />
        {searchFilter && (
          <button
            onClick={() => setSearchFilter('')}
            className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 text-zinc-500 hover:text-zinc-300"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Track list */}
      {tracks.length > 0 ? (
        <div>
          <PlaylistColumnHeader
            columns={columns}
            gridColumns={gridColumns}
            sortBy={sortBy}
            sortOrder={sortOrder}
            toggleSort={toggleSort}
          />
          <div className="space-y-1">
            {tracks.map((track, idx) => {
              const fullTrack = getTrackFromItem(track);
              return (
                <div key={track.id}>
                  {/* Mobile layout */}
                  <div
                    onClick={() => handlePlay(idx)}
                    onContextMenu={(e) => handleContextMenu(fullTrack, e)}
                    className={`sm:hidden flex items-center gap-3 px-4 py-3 rounded-lg hover:bg-zinc-800/50 cursor-pointer transition-colors ${
                      currentTrack?.id === track.id ? 'bg-zinc-800/30' : ''
                    }`}
                  >
                    <div className="w-8 flex-shrink-0 text-center" onClick={(e) => { e.stopPropagation(); handlePlay(idx); }}>
                      <PlayIndicator isCurrent={currentTrack?.id === track.id} isPlaying={isPlaying} index={idx + 1} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className={`font-medium truncate ${currentTrack?.id === track.id ? 'text-green-500' : ''}`}>
                        {track.title || 'Unknown Title'}
                      </div>
                      <div className="text-sm text-zinc-400 truncate">
                        {track.artist || 'Unknown Artist'}
                        {track.album && <span className="text-zinc-500"> • {track.album}</span>}
                      </div>
                    </div>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleFavorite(track.id);
                      }}
                      className={`flex-shrink-0 p-1 transition-colors ${
                        isFavorite(track.id)
                          ? 'text-pink-500 hover:text-pink-400'
                          : 'text-zinc-500 hover:text-pink-400'
                      }`}
                    >
                      <Heart className="w-4 h-4" fill={isFavorite(track.id) ? 'currentColor' : 'none'} />
                    </button>
                    <div className="flex-shrink-0 text-sm text-zinc-500">
                      {formatDuration(track.duration_seconds)}
                    </div>
                  </div>
                  {/* Desktop layout */}
                  <div
                    draggable
                    onDragStart={(e) => {
                      e.dataTransfer.setData('application/track-id', track.id);
                      e.dataTransfer.effectAllowed = 'copy';
                    }}
                    onClick={() => handlePlay(idx)}
                    onContextMenu={(e) => handleContextMenu(fullTrack, e)}
                    className={`hidden sm:grid group gap-4 px-4 py-2 items-center rounded-lg hover:bg-zinc-800/50 cursor-pointer transition-all ${
                      currentTrack?.id === track.id ? 'bg-zinc-800/30' : ''
                    }`}
                    style={{ gridTemplateColumns: gridColumns }}
                  >
                  {/* Track number / Play button */}
                  <div className="w-8 text-center">
                    <PlayIndicator isCurrent={currentTrack?.id === track.id} isPlaying={isPlaying} index={idx + 1} />
                  </div>

                  {/* Title + artist */}
                  <div className="min-w-0">
                    <div className={`font-medium truncate ${currentTrack?.id === track.id ? 'text-green-500' : ''}`}>
                      {track.title || 'Unknown Title'}
                    </div>
                    <div className="text-sm text-zinc-400 truncate sm:hidden">
                      {track.artist || 'Unknown Artist'}
                      {track.album && <span className="text-zinc-500"> • {track.album}</span>}
                    </div>
                  </div>

                  {/* Dynamic columns */}
                  {visibleColumnIds.map((colId) => {
                    const colDef = getColumnDef(colId);
                    if (!colDef) return <div key={colId} />;
                    const raw = colDef.getValue(fullTrack);
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

                  {/* Favorite button */}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      toggleFavorite(track.id);
                    }}
                    className={`p-1 transition-colors ${
                      isFavorite(track.id)
                        ? 'text-pink-500 hover:text-pink-400'
                        : 'text-zinc-500 hover:text-pink-400 opacity-100 sm:opacity-0 sm:group-hover:opacity-100'
                    }`}
                    title={isFavorite(track.id) ? 'Remove from favorites' : 'Add to favorites'}
                  >
                    <Heart className="w-4 h-4" fill={isFavorite(track.id) ? 'currentColor' : 'none'} />
                  </button>

                  {/* Duration */}
                  <div className="text-sm text-zinc-500 text-right">
                    {formatDuration(track.duration_seconds)}
                  </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ) : (
        <div className="text-center py-12 text-zinc-500">
          <Music className="w-12 h-12 mx-auto mb-3 opacity-50" />
          <p>No tracks match these rules</p>
        </div>
      )}

      {/* Discovery section */}
      {tracks.length > 0 && (
        <SmartPlaylistDiscoverySection
          sections={discoverySections}
          hasDiscovery={hasDiscovery}
          loading={discoverLoading}
          onGoToArtist={(artistName) => {
            navigateToArtist(artistName);
          }}
          onPlayTrack={(item) => {
            if (item.id) {
              if (currentTrack?.id === item.id) {
                setIsPlaying(!isPlaying);
                return;
              }
              // Play the track
              setQueue([{
                id: item.id,
                file_path: '',
                title: item.name,
                artist: item.playbackContext?.artist || item.subtitle || null,
                album: item.playbackContext?.album || null,
                album_artist: null,
                album_type: 'album' as const,
                track_number: null,
                disc_number: null,
                year: null,
                genre: null,
                duration_seconds: null,
                format: null,
                analysis_version: 0,
              }]);
            }
          }}
        />
      )}

      {/* Context menu */}
      {contextMenu.isOpen && contextMenu.track && (
        <TrackContextMenu
          track={contextMenu.track}
          position={contextMenu.position}
          isSelected={false}
          onClose={closeContextMenu}
          onPlay={() => {
            const idx = tracks.findIndex(t => t.id === contextMenu.track?.id);
            if (idx !== -1) handlePlay(idx);
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
          onToggleSelect={() => {}}
          onAddToPlaylist={() => {}}
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
        />
      )}
    </div>
  );
}
