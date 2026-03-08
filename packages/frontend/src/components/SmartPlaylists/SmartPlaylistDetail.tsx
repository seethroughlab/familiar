import { useState, useEffect, useCallback, useMemo } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Play, Loader2, Zap, Clock, Download, Check, RefreshCw, CloudOff, Search, X, RotateCw } from 'lucide-react';
import { smartPlaylistsApi, tracksApi } from '../../api';
import type { SmartPlaylist, SmartPlaylistTracksResponse } from '../../api';
import { usePlayerStore } from '../../stores/playerStore';
import { useDownloadStore, getSmartPlaylistJobId } from '../../stores/downloadStore';
import { useOfflineStatus } from '../../hooks/useOfflineStatus';
import { useAutoDownload } from '../../hooks/useAutoDownload';
import * as offlineService from '../../services/offlineService';
import * as playlistCache from '../../services/playlistCache';
import type { Track } from '../../types';
import { DiscoveryPanel, useTrackDiscovery, type DiscoveryItem } from '../Discovery';
import { PlaylistTrackList } from '../shared/PlaylistTrackList';

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

  return (
    <div className="mt-6 border-t border-zinc-800 pt-4">
      <DiscoveryPanel
        title="Discover More"
        sections={sections}
        collapsible
        defaultExpanded
        onItemClick={handleItemClick}
        onItemPlay={onPlayTrack}
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

  const currentTrack = usePlayerStore((s) => s.currentTrack);
  const isPlaying = usePlayerStore((s) => s.isPlaying);
  const setQueue = usePlayerStore((s) => s.setQueue);
  const setQueueByTrackId = usePlayerStore((s) => s.setQueueByTrackId);
  const setIsPlaying = usePlayerStore((s) => s.setIsPlaying);
  const { isOffline } = useOfflineStatus();
  const { navigateToArtist } = useAppNavigation();
  const [offlineTrackIds, setOfflineTrackIds] = useState<Set<string>>(new Set());
  const [usingCachedData, setUsingCachedData] = useState(false);
  const [showDownloadedOnly, setShowDownloadedOnly] = useState(false);
  const [searchFilter, setSearchFilter] = useState('');

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
  const playlistId = playlist?.id ?? '';
  const jobId = getSmartPlaylistJobId(playlistId);
  const downloadJob = jobs.get(jobId);
  const isDownloading = downloadJob?.status === 'downloading' || downloadJob?.status === 'queued';
  const downloadProgress = {
    current: downloadJob ? downloadJob.completedIds.length + (downloadJob.currentProgress > 0 ? 1 : 0) : 0,
    total: downloadJob?.trackIds.length ?? 0,
  };

  // Fetch tracks for this smart playlist with offline fallback
  const { data: tracksResponse, isLoading: tracksLoading, refetch } = useQuery({
    queryKey: ['smart-playlist-tracks', playlistId],
    queryFn: async () => {
      try {
        const result = await smartPlaylistsApi.getTracks(playlistId, 500);
        setUsingCachedData(false);

        // Cache the smart playlist with its track IDs
        if (playlist) {
          await playlistCache.cacheSmartPlaylist(
            playlist,
            result.tracks.map((t) => t.id)
          );
        }
        await playlistCache.cacheTrackMetadata(result.tracks);

        return result;
      } catch (error) {
        // If offline, try to load from cache
        if (isOffline) {
          const cached = await playlistCache.getCachedSmartPlaylist(playlistId);
          if (cached) {
            // Resolve track metadata from cached tracks
            const resolvedTracks = await playlistCache.resolveTrackIds(cached.track_ids);
            setUsingCachedData(true);
            return {
              playlist: {
                ...playlist!,
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
    enabled: !!playlist,
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

  // Fetch discovery data based on the first track in the playlist (not available offline)
  const firstTrackId = filteredTracks[0]?.id;
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

  // Check which tracks are already offline
  useEffect(() => {
    const checkOfflineStatus = async () => {
      const ids = await offlineService.getOfflineTrackIds();
      setOfflineTrackIds(new Set(ids));
    };
    checkOfflineStatus();
  }, []);

  // Update offline track IDs when download job completes
  useEffect(() => {
    if (downloadJob?.status === 'completed' || downloadJob?.status === 'failed') {
      // Refresh offline IDs after download completes
      offlineService.getOfflineTrackIds().then((ids) => {
        setOfflineTrackIds(new Set(ids));
      });
    }
  }, [downloadJob?.status]);

  const allTrackIds = useMemo(() => allTracks.map(t => t.id), [allTracks]);

  // Auto-download new tracks when enabled
  useAutoDownload({
    enabled: playlist?.auto_download ?? false,
    jobId,
    jobType: 'smart-playlist',
    jobName: playlist?.name ?? '',
    trackIds: allTrackIds,
  });

  if (!playlist) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-6 h-6 animate-spin text-zinc-400" />
      </div>
    );
  }

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

  const allTracksOffline = allTracks.every(t => offlineTrackIds.has(t.id));
  const offlineCount = allTracks.filter(t => offlineTrackIds.has(t.id)).length;

  const handlePlay = (startIndex = 0, sortedItems?: SmartPlaylistTracksResponse['tracks']) => {
    const items = sortedItems ?? filteredTracks;
    if (items.length === 0) return;

    // If clicking on the currently playing track, toggle play/pause
    const clickedTrack = items[startIndex];
    if (!clickedTrack) return;
    if (currentTrack?.id === clickedTrack.id) {
      setIsPlaying(!isPlaying);
      return;
    }

    const queueTracks = items.map(t => getTrackFromItem(t));
    setQueueByTrackId(queueTracks, clickedTrack.id);
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
      not_equals: '\u2260',
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

  const totalDuration = filteredTracks.reduce(
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
            <span>{filteredTracks.length} tracks</span>
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
            disabled={filteredTracks.length === 0}
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
      <PlaylistTrackList
        items={filteredTracks}
        getTrack={getTrackFromItem}
        onPlay={handlePlay}
        emptyMessage="No tracks match these rules"
        sortPersistKey={`smart-playlist-${playlistId}`}
      />

      {/* Discovery section */}
      {filteredTracks.length > 0 && (
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
    </div>
  );
}

// Import needed for navigateToArtist
import { useAppNavigation } from '../../hooks/useAppNavigation';
