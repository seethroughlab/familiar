import { useState, useCallback, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import { playlistsApi } from '../api';
import { queryKeys } from '../api/queryKeys';
import { useDownloadStore, getPlaylistJobId, type DownloadJob } from '../stores/downloadStore';
import { useOfflineStatus } from '../hooks/useOfflineStatus';
import { STALE_TIME, offlineAwareRetry } from '../api/queryDefaults';
import { useAutoDownload } from '../hooks/useAutoDownload';
import { useOfflineTrackState } from '../hooks/useOfflineTrackState';
import { useTrackSearch } from '../hooks/useTrackSearch';
import * as playlistCache from '../services/playlistCache';
import type { Track } from '../types';
import type { PlaylistDetail as PlaylistDetailType, PlaylistTrack as PlaylistTrackType } from '../api';

export interface UsePlaylistDetailDataResult {
  playlistId: string;
  playlist: PlaylistDetailType | undefined;
  isLoading: boolean;
  recommendations: RecommendationsResponse | undefined;
  recommendationsLoading: boolean;
  usingCachedData: boolean;

  // Download
  downloadJob: DownloadJob | undefined;
  isDownloading: boolean;
  downloadProgress: { current: number; total: number };
  startDownload: (id: string, type: DownloadJob['type'], name: string, trackIds: string[]) => void;
  jobId: string;

  // Offline + filtering
  offlineTrackIds: Set<string>;
  localTracks: PlaylistTrackType[];
  allTracksOffline: boolean;
  offlineCount: number;
  searchFilter: string;
  setSearchFilter: (v: string) => void;
  showDownloadedOnly: boolean;
  setShowDownloadedOnly: (v: boolean) => void;
  filteredTracks: PlaylistTrackType[];

  // Helpers
  getTrackFromPlaylistItem: (t: PlaylistTrackType) => Track | null;
  totalDuration: number;
  isOffline: boolean;
}

type RecommendationsResponse = {
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
};

export function usePlaylistDetailData(
  playlistIdProp?: string,
): UsePlaylistDetailDataResult {
  const routeParams = useParams<{ id: string }>();
  const playlistId = playlistIdProp || routeParams.id || '';
  const { isOffline } = useOfflineStatus();
  const [usingCachedData, setUsingCachedData] = useState(false);

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

  // Download store
  const { jobs, startDownload } = useDownloadStore();
  const jobId = getPlaylistJobId(playlistId);
  const downloadJob = jobs.get(jobId);
  const isDownloading = downloadJob?.status === 'downloading' || downloadJob?.status === 'queued';
  const downloadProgress = {
    current: downloadJob ? downloadJob.completedIds.length + (downloadJob.currentProgress > 0 ? 1 : 0) : 0,
    total: downloadJob?.trackIds.length ?? 0,
  };

  // Playlist query with offline cache fallback
  const { data: playlist, isLoading } = useQuery({
    queryKey: queryKeys.playlist.detail(playlistId),
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
    retry: offlineAwareRetry(isOffline),
  });

  // Fetch recommendations for AI-generated playlists
  const { data: recommendations, isLoading: recommendationsLoading } = useQuery({
    queryKey: queryKeys.playlistRecommendations.detail(playlistId),
    queryFn: () => playlistsApi.getRecommendations(playlistId),
    staleTime: STALE_TIME.EXTRA_LONG,
    retry: 1,
    enabled: !!playlist?.is_auto_generated && !isOffline && !usingCachedData,
  });

  // Offline track state
  const { offlineTrackIds } = useOfflineTrackState({ downloadJobStatus: downloadJob?.status });

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
  const playlistTracks = playlist?.tracks ?? [];
  const { searchFilter, setSearchFilter, showDownloadedOnly, setShowDownloadedOnly, filteredTracks } = useTrackSearch(playlistTracks, offlineTrackIds);

  const totalDuration = playlist?.tracks.reduce(
    (sum, t) => sum + (t.duration_seconds || 0),
    0
  ) || 0;

  return {
    playlistId,
    playlist,
    isLoading,
    recommendations,
    recommendationsLoading,
    usingCachedData,
    downloadJob,
    isDownloading,
    downloadProgress,
    startDownload,
    jobId,
    offlineTrackIds,
    localTracks,
    allTracksOffline,
    offlineCount,
    searchFilter,
    setSearchFilter,
    showDownloadedOnly,
    setShowDownloadedOnly,
    filteredTracks,
    getTrackFromPlaylistItem,
    totalDuration,
    isOffline,
  };
}
