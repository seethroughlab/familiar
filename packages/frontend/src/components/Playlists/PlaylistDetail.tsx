import { useState, useEffect, useCallback, useMemo } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Play, Loader2, Sparkles, Clock, Download, Check, WifiOff, Heart, GripVertical, X, ListPlus, Trash2, CloudOff, Search, RotateCw } from 'lucide-react';
import { playlistsApi, tracksApi } from '../../api';
import { showError } from '../../stores/toastStore';
import { usePlayerStore } from '../../stores/playerStore';
import { useDownloadStore, getPlaylistJobId } from '../../stores/downloadStore';
import { useFavorites } from '../../hooks/useFavorites';
import { useOfflineStatus } from '../../hooks/useOfflineStatus';
import { useAppNavigation } from '../../hooks/useAppNavigation';
import { useAutoDownload } from '../../hooks/useAutoDownload';
import { DiscoveryPanel, usePlaylistDiscovery, type DiscoveryItem } from '../Discovery';
import * as offlineService from '../../services/offlineService';
import * as playlistCache from '../../services/playlistCache';
import type { Track } from '../../types';
import type { PlaylistDetail as PlaylistDetailType, PlaylistTrack as PlaylistTrackType } from '../../api';
import { PlaylistTrackList, type TrackRowContext } from '../shared/PlaylistTrackList';
import { formatDuration } from '../../utils/format';

import { createLogger } from '../../utils/logger';

const log = createLogger('PlaylistDetail');

// Playlist Discovery Section using unified components
function PlaylistDiscoverySection({
  recommendations,
  loading,
  onGoToArtist,
  onPlayItem,
}: {
  recommendations: {
    artists: Array<{
      name: string;
      source: string;
      match_score: number;
      image_url: string | null;
      external_url: string | null;
      local_track_count: number;
    }>;
    tracks: Array<{
      title: string;
      artist: string;
      source: string;
      match_score: number;
      external_url: string | null;
      local_track_id: string | null;
      album: string | null;
    }>;
    sources_used: string[];
  } | undefined;
  loading: boolean;
  onGoToArtist: (artistName: string) => void;
  onPlayItem: (item: DiscoveryItem) => void;
}) {
  const { sections, sources, hasDiscovery } = usePlaylistDiscovery({ recommendations });

  if (loading) {
    return (
      <div className="mt-6 border-t border-zinc-800 pt-4">
        <DiscoveryPanel
          sections={[]}
          loading={true}
        />
      </div>
    );
  }

  if (!hasDiscovery) return null;

  const handleItemClick = (item: DiscoveryItem) => {
    if (item.entityType === 'artist' && item.inLibrary) {
      onGoToArtist(item.name);
    }
  };

  return (
    <div className="mt-6 border-t border-zinc-800 pt-4">
      <DiscoveryPanel
        title="Discover More"
        sections={sections}
        sources={sources}
        collapsible
        defaultExpanded
        onItemClick={handleItemClick}
        onItemPlay={onPlayItem}
      />
    </div>
  );
}

interface Props {
  playlistId?: string;
  onBack?: () => void;
}

export function PlaylistDetail({ playlistId: playlistIdProp, onBack: onBackProp }: Props) {
  const routeParams = useParams<{ id: string }>();
  const routeNavigate = useNavigate();
  const playlistId = playlistIdProp || routeParams.id || '';
  const onBack = onBackProp || (() => routeNavigate(-1));
  const queryClient = useQueryClient();
  const currentTrack = usePlayerStore((s) => s.currentTrack);
  const isPlaying = usePlayerStore((s) => s.isPlaying);
  const setQueue = usePlayerStore((s) => s.setQueue);
  const setQueueByTrackId = usePlayerStore((s) => s.setQueueByTrackId);
  const addToQueue = usePlayerStore((s) => s.addToQueue);
  const setIsPlaying = usePlayerStore((s) => s.setIsPlaying);
  const { isFavorite, toggle: toggleFavorite } = useFavorites();
  const { isOffline } = useOfflineStatus();
  const { navigateToArtist } = useAppNavigation();
  const [offlineTrackIds, setOfflineTrackIds] = useState<Set<string>>(new Set());
  const [usingCachedData, setUsingCachedData] = useState(false);
  const [showDownloadedOnly, setShowDownloadedOnly] = useState(false);
  const [searchFilter, setSearchFilter] = useState('');

  const getTrackFromPlaylistItem = useCallback(
    (t: PlaylistTrackType): Track | null => {
      return {
        id: t.id,
        file_path: '',
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
      };
    },
    [],
  );

  // Use global download store
  const { jobs, startDownload } = useDownloadStore();
  const jobId = getPlaylistJobId(playlistId);
  const downloadJob = jobs.get(jobId);
  const isDownloading = downloadJob?.status === 'downloading' || downloadJob?.status === 'queued';
  const downloadProgress = {
    current: downloadJob ? downloadJob.completedIds.length + (downloadJob.currentProgress > 0 ? 1 : 0) : 0,
    total: downloadJob?.trackIds.length ?? 0,
  };

  // Drag-to-reorder state
  const [draggedTrackId, setDraggedTrackId] = useState<string | null>(null);
  const [dropTargetId, setDropTargetId] = useState<string | null>(null);

  const { data: playlist, isLoading } = useQuery({
    queryKey: ['playlist', playlistId],
    queryFn: async () => {
      try {
        const data = await playlistsApi.get(playlistId);
        await playlistCache.cachePlaylist(data);
        setUsingCachedData(false);
        return data;
      } catch (error) {
        if (isOffline) {
          const cached = await playlistCache.getCachedPlaylist(playlistId);
          if (cached) {
            const tracks = await playlistCache.resolveTrackIds(cached.track_ids);
            setUsingCachedData(true);
            return {
              id: cached.id,
              name: cached.name,
              description: cached.description,
              is_auto_generated: cached.is_auto_generated,
              generation_prompt: cached.generation_prompt,
              tracks: tracks.map((t, idx) => ({
                id: t.id,
                playlist_track_id: t.id,
                type: 'local' as const,
                title: t.title,
                artist: t.artist,
                album: t.album,
                duration_seconds: t.durationSeconds,
                position: idx,
              })),
              created_at: '',
              updated_at: '',
            } as PlaylistDetailType;
          }
        }
        throw error;
      }
    },
    retry: isOffline ? false : 3,
  });

  // Fetch recommendations for AI-generated playlists
  const { data: recommendations, isLoading: recommendationsLoading } = useQuery({
    queryKey: ['playlist-recommendations', playlistId],
    queryFn: () => playlistsApi.getRecommendations(playlistId),
    staleTime: 1000 * 60 * 10,
    retry: 1,
    enabled: !!playlist?.is_auto_generated && !isOffline && !usingCachedData,
  });

  // Check which tracks are already offline
  useEffect(() => {
    const checkOfflineStatus = async () => {
      const ids = await offlineService.getOfflineTrackIds();
      setOfflineTrackIds(new Set(ids));
    };
    checkOfflineStatus();
  }, []);

  const handleDownloadPlaylist = async () => {
    if (!playlist || playlist.tracks.length === 0) return;
    const localTracks = playlist.tracks.filter(t => t.type === 'local');
    const tracksToDownload = localTracks.filter((t) => !offlineTrackIds.has(t.id));
    if (tracksToDownload.length === 0) return;
    startDownload(jobId, 'playlist', playlist.name, tracksToDownload.map((t) => t.id));
    await playlistCache.cachePlaylist(playlist);
  };

  // Update offline track IDs when download job completes
  useEffect(() => {
    if (downloadJob?.status === 'completed' || downloadJob?.status === 'failed') {
      offlineService.getOfflineTrackIds().then((ids) => {
        setOfflineTrackIds(new Set(ids));
      });
    }
  }, [downloadJob?.status]);

  // Count only local tracks for offline status
  const localTracks = playlist?.tracks.filter(t => t.type === 'local') ?? [];
  const localTrackIds = useMemo(() => localTracks.map(t => t.id), [localTracks]);
  const allTracksOffline = localTracks.length > 0 && localTracks.every(t => offlineTrackIds.has(t.id));
  const offlineCount = localTracks.filter(t => offlineTrackIds.has(t.id)).length;

  // Auto-download new tracks when enabled
  useAutoDownload({
    enabled: playlist?.auto_download ?? false,
    jobId,
    jobType: 'playlist',
    jobName: playlist?.name ?? '',
    trackIds: localTrackIds,
  });

  // Filter by downloaded tracks and search query
  const filteredTracks = useMemo(() => {
    if (!playlist) return [];
    let result = playlist.tracks;
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
  }, [playlist, showDownloadedOnly, offlineTrackIds, searchFilter]);

  const handlePlay = useCallback((startIndex = 0, sortedItems?: PlaylistTrackType[]) => {
    const items = sortedItems ?? filteredTracks;
    if (items.length === 0) return;

    const clickedTrack = items[startIndex];
    if (!clickedTrack) return;
    if (currentTrack?.id === clickedTrack.id) {
      setIsPlaying(!isPlaying);
      return;
    }

    const queueTracks = items.map(t => ({
      id: t.id,
      file_path: '',
      title: t.title || 'Unknown',
      artist: t.artist || 'Unknown',
      album: t.album || null,
      album_artist: t.album_artist ?? null,
      album_type: (t.album_type as Track['album_type']) ?? 'album',
      track_number: t.track_number ?? null,
      disc_number: t.disc_number ?? null,
      year: t.year ?? null,
      genre: t.genre ?? null,
      duration_seconds: t.duration_seconds || null,
      format: t.format ?? null,
      analysis_version: t.analysis_version ?? 0,
    }));
    setQueueByTrackId(queueTracks, clickedTrack.id, { type: 'playlist', id: playlistId });
  }, [filteredTracks, currentTrack?.id, isPlaying, setIsPlaying, setQueueByTrackId, playlistId]);

  // Handle playing a discovery item
  const handlePlayDiscoveryItem = useCallback(async (item: DiscoveryItem) => {
    if (item.entityType === 'track' && item.id) {
      if (currentTrack?.id === item.id) {
        setIsPlaying(!isPlaying);
        return;
      }
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
    } else if (item.entityType === 'artist' && item.inLibrary) {
      try {
        const response = await tracksApi.list({ artist: item.name, page_size: 50 });
        if (response.items.length > 0) {
          setQueue(response.items, 0);
        }
      } catch (error) {
        log.error('Failed to fetch artist tracks:', error);
        showError('Failed to load artist tracks');
      }
    }
  }, [currentTrack?.id, isPlaying, setIsPlaying, setQueue]);

  // Drag-to-reorder handlers
  const handleDragStart = useCallback((playlistTrackId: string, trackId: string, e: React.DragEvent) => {
    setDraggedTrackId(playlistTrackId);
    e.dataTransfer.effectAllowed = 'copyMove';
    e.dataTransfer.setData('text/plain', playlistTrackId);
    e.dataTransfer.setData('application/track-id', trackId);
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent, targetId: string) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    if (targetId !== draggedTrackId) {
      setDropTargetId(targetId);
    }
  }, [draggedTrackId]);

  const handleDragLeave = useCallback(() => {
    setDropTargetId(null);
  }, []);

  const handleDrop = useCallback(async (targetId: string) => {
    if (!playlist || !draggedTrackId || draggedTrackId === targetId) {
      setDraggedTrackId(null);
      setDropTargetId(null);
      return;
    }

    const tracks = [...playlist.tracks];
    const draggedIndex = tracks.findIndex(t => t.playlist_track_id === draggedTrackId);
    const targetIndex = tracks.findIndex(t => t.playlist_track_id === targetId);

    if (draggedIndex === -1 || targetIndex === -1) {
      setDraggedTrackId(null);
      setDropTargetId(null);
      return;
    }

    const [draggedTrack] = tracks.splice(draggedIndex, 1);
    tracks.splice(targetIndex, 0, draggedTrack);

    queryClient.setQueryData(['playlist', playlistId], (old: PlaylistDetailType | undefined) => {
      if (!old) return old;
      return { ...old, tracks };
    });

    setDraggedTrackId(null);
    setDropTargetId(null);

    try {
      await playlistsApi.reorderItems(playlistId, tracks.map(t => t.playlist_track_id));
    } catch (error) {
      log.error('Failed to reorder tracks:', error);
      showError('Failed to reorder tracks');
      queryClient.invalidateQueries({ queryKey: ['playlist', playlistId] });
    }
  }, [playlist, draggedTrackId, playlistId, queryClient]);

  const handleDragEnd = useCallback(() => {
    setDraggedTrackId(null);
    setDropTargetId(null);
  }, []);

  // Bulk action handlers
  const handleQueueSelected = useCallback((selectedIds: Set<string>) => {
    if (!playlist) return;
    const selectedTracks = playlist.tracks.filter(t => selectedIds.has(t.playlist_track_id));
    selectedTracks.forEach(track => {
      addToQueue({
        id: track.id,
        file_path: '',
        title: track.title || 'Unknown',
        artist: track.artist || 'Unknown',
        album: track.album || null,
        album_artist: null,
        album_type: 'album',
        track_number: null,
        disc_number: null,
        year: null,
        genre: null,
        duration_seconds: track.duration_seconds || null,
        format: null,
        analysis_version: 0,
      });
    });
  }, [playlist, addToQueue]);

  const handleRemoveFromPlaylist = useCallback(async (track: Track) => {
    if (!playlist) return;
    const playlistTrack = playlist.tracks.find(t => {
      return t.id === track.id;
    });
    if (!playlistTrack) return;

    // Optimistically remove from cache
    const previousTracks = playlist.tracks;
    queryClient.setQueryData(['playlist', playlistId], (old: PlaylistDetailType | undefined) => {
      if (!old) return old;
      return { ...old, tracks: old.tracks.filter(t => t.playlist_track_id !== playlistTrack.playlist_track_id) };
    });

    try {
      await playlistsApi.removeItem(playlistId, playlistTrack.playlist_track_id);
    } catch (error) {
      log.error('Failed to remove track from playlist:', error);
      showError('Failed to remove track');
      // Rollback
      queryClient.setQueryData(['playlist', playlistId], (old: PlaylistDetailType | undefined) => {
        if (!old) return old;
        return { ...old, tracks: previousTracks };
      });
    }
  }, [playlist, playlistId, queryClient]);

  const handleRemoveSelected = useCallback(async (selectedIds: Set<string>, clearSelection: () => void) => {
    if (!playlist) return;
    const remainingTracks = playlist.tracks.filter(t => !selectedIds.has(t.playlist_track_id));

    queryClient.setQueryData(['playlist', playlistId], (old: PlaylistDetailType | undefined) => {
      if (!old) return old;
      return { ...old, tracks: remainingTracks };
    });

    clearSelection();

    try {
      await playlistsApi.reorderTracks(playlistId, remainingTracks.map(t => t.id));
    } catch (error) {
      log.error('Failed to remove tracks:', error);
      showError('Failed to remove tracks');
      queryClient.invalidateQueries({ queryKey: ['playlist', playlistId] });
    }
  }, [playlist, playlistId, queryClient]);

  const totalDuration = playlist?.tracks.reduce(
    (sum, t) => sum + (t.duration_seconds || 0),
    0
  ) || 0;

  // Item ID uses playlist_track_id for uniqueness (supports duplicate tracks)
  const getItemId = useCallback((t: PlaylistTrackType) => t.playlist_track_id, []);

  // Render props
  const renderTitleBadge = useCallback((_ctx: TrackRowContext<PlaylistTrackType>) => {
    return null;
  }, []);

  const getRowClassName = useCallback((_ctx: TrackRowContext<PlaylistTrackType>) => {
    return '';
  }, []);

  const renderDesktopTrailing = useCallback((ctx: TrackRowContext<PlaylistTrackType>) => {
    const track = ctx.item;

    return (
      <>
        {/* Heart */}
        <div className="flex items-center gap-0.5">
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
        </div>

        {/* Offline indicator */}
        <div>
          {offlineTrackIds.has(track.id) && (
            <span title="Available offline">
              <WifiOff className="w-4 h-4 text-green-500" />
            </span>
          )}
        </div>

        {/* Duration */}
        <div className="text-sm text-zinc-500 text-right">
          {formatDuration(track.duration_seconds)}
        </div>
      </>
    );
  }, [isFavorite, toggleFavorite, offlineTrackIds]);

  const renderMobileTrailing = useCallback((ctx: TrackRowContext<PlaylistTrackType>) => {
    const track = ctx.item;

    return (
      <>
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
      </>
    );
  }, [isFavorite, toggleFavorite]);

  const renderDragHandle = useCallback((_ctx: TrackRowContext<PlaylistTrackType>) => {
    if (isOffline || usingCachedData) return null;
    return (
      <div className="mr-0.5 transition-opacity opacity-0 group-hover:opacity-50 hover:!opacity-100 cursor-grab active:cursor-grabbing">
        <GripVertical className="w-3 h-3 text-zinc-500" />
      </div>
    );
  }, [isOffline, usingCachedData]);

  const renderBulkActions = useCallback((selectedIds: Set<string>, clearSelection: () => void) => (
    <>
      <button
        onClick={() => { handleQueueSelected(selectedIds); clearSelection(); }}
        className="flex items-center gap-1.5 px-3 py-1.5 bg-zinc-700 hover:bg-zinc-600 rounded-md text-sm transition-colors"
      >
        <ListPlus className="w-4 h-4" />
        Add to Queue
      </button>
      {!isOffline && !usingCachedData && (
        <button
          onClick={() => handleRemoveSelected(selectedIds, clearSelection)}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-red-600/20 hover:bg-red-600/30 text-red-400 rounded-md text-sm transition-colors"
        >
          <Trash2 className="w-4 h-4" />
          Remove
        </button>
      )}
    </>
  ), [handleQueueSelected, handleRemoveSelected, isOffline, usingCachedData]);

  // Drag reorder config
  const dragReorderDisabled = isOffline || usingCachedData;
  const dragReorder = useMemo(() => ({
    onDragStart: (item: PlaylistTrackType, e: React.DragEvent) => handleDragStart(item.playlist_track_id, item.id, e),
    onDragOver: (item: PlaylistTrackType, e: React.DragEvent) => handleDragOver(e, item.playlist_track_id),
    onDragLeave: handleDragLeave,
    onDrop: (item: PlaylistTrackType) => handleDrop(item.playlist_track_id),
    onDragEnd: handleDragEnd,
    isDragged: (item: PlaylistTrackType) => draggedTrackId === item.playlist_track_id,
    isDropTarget: (item: PlaylistTrackType) => dropTargetId === item.playlist_track_id,
    disabled: dragReorderDisabled,
  }), [handleDragStart, handleDragOver, handleDragLeave, handleDrop, handleDragEnd, draggedTrackId, dropTargetId, dragReorderDisabled]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-6 h-6 animate-spin text-zinc-400" />
      </div>
    );
  }

  if (!playlist) {
    return (
      <div className="text-center py-12 text-zinc-500">
        <p>Playlist not found</p>
        <button
          onClick={onBack}
          className="mt-4 text-green-500 hover:text-green-400"
        >
          Go back
        </button>
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
            {playlist.is_auto_generated && (
              <Sparkles className="w-5 h-5 text-purple-400 flex-shrink-0" />
            )}
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
            <span>{playlist.tracks.length} tracks</span>
            <span className="flex items-center gap-1">
              <Clock className="w-4 h-4" />
              {Math.floor(totalDuration / 60)} min
            </span>
            {playlist.is_auto_generated && playlist.generation_prompt && (
              <span className="text-purple-400/70 truncate max-w-full sm:max-w-xs">
                "{playlist.generation_prompt}"
              </span>
            )}
          </div>
        </div>

        {/* Action buttons */}
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
          <button
            onClick={() => handlePlay()}
            disabled={filteredTracks.length === 0}
            className="flex items-center justify-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-500 disabled:opacity-50 disabled:hover:bg-green-600 rounded-full transition-colors"
          >
            <Play className="w-4 h-4" fill="currentColor" />
            Play
          </button>

          <button
            onClick={handleDownloadPlaylist}
            disabled={playlist.tracks.length === 0 || isDownloading || allTracksOffline || isOffline}
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
                  {offlineCount > 0 ? `${offlineCount}/${playlist.tracks.length}` : 'Download'}
                </span>
              </>
            )}
          </button>

          {/* Auto-download toggle */}
          <button
            onClick={async () => {
              if (!playlist) return;
              const newValue = !playlist.auto_download;
              await playlistsApi.update(playlist.id, { auto_download: newValue });
              queryClient.setQueryData(['playlist', playlistId], (old: PlaylistDetailType | undefined) =>
                old ? { ...old, auto_download: newValue } : old
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
      <PlaylistTrackList
        items={filteredTracks}
        getTrack={getTrackFromPlaylistItem}
        getItemId={getItemId}
        onPlay={handlePlay}
        trailingColumns={['3rem', '3rem', '4.5rem']}
        renderDesktopTrailing={renderDesktopTrailing}
        renderMobileTrailing={renderMobileTrailing}
        renderTitleBadge={renderTitleBadge}
        getRowClassName={getRowClassName}
        renderBulkActions={renderBulkActions}
        dragReorder={dragReorder}
        renderDragHandle={renderDragHandle}
        contextMenuOptions={{ onRemoveFromPlaylist: handleRemoveFromPlaylist }}
        emptyMessage="No tracks in this playlist"
        sortPersistKey={`playlist-${playlistId}`}
      />

      {/* Recommendations (only for AI-generated playlists) */}
      {playlist.is_auto_generated && (
        <PlaylistDiscoverySection
          recommendations={recommendations}
          loading={recommendationsLoading}
          onGoToArtist={(artistName) => {
            navigateToArtist(artistName);
          }}
          onPlayItem={handlePlayDiscoveryItem}
        />
      )}
    </div>
  );
}
