import { useState, useEffect, useCallback, useMemo } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Play, Heart, Clock, Search, X, Download, Check, Loader2, RotateCw, ExternalLink } from 'lucide-react';
import { favoritesApi } from '../../api';
import { usePlayerStore } from '../../stores/playerStore';
import { useAudioSettingsStore } from '../../stores/audioSettingsStore';
import { useDownloadStore } from '../../stores/downloadStore';
import { useFavorites } from '../../hooks/useFavorites';
import { useOfflineStatus } from '../../hooks/useOfflineStatus';
import { useAutoDownload } from '../../hooks/useAutoDownload';
import * as offlineService from '../../services/offlineService';
import type { Track } from '../../types';
import type { FavoriteTrack, ExternalFavoriteTrack } from '../../api';
import { PlaylistTrackList, type TrackRowContext } from '../shared/PlaylistTrackList';
import { StoreSearchLinks } from '../shared/StoreSearchLinks';
import { formatDuration } from '../../utils/format';

type FavoriteItem =
  | (FavoriteTrack & { _kind: 'local' })
  | (ExternalFavoriteTrack & { _kind: 'external' });

interface Props {
  onBack?: () => void;
}

export function FavoritesDetail({ onBack: onBackProp }: Props) {
  const routeNavigate = useNavigate();
  const onBack = onBackProp || (() => routeNavigate(-1));
  const queryClient = useQueryClient();
  const currentTrack = usePlayerStore((s) => s.currentTrack);
  const isPlaying = usePlayerStore((s) => s.isPlaying);
  const setQueue = usePlayerStore((s) => s.setQueue);
  const setIsPlaying = usePlayerStore((s) => s.setIsPlaying);
  const playExternalPreviews = useAudioSettingsStore((s) => s.playExternalPreviews);
  const setPlayExternalPreviews = useAudioSettingsStore((s) => s.setPlayExternalPreviews);
  const { favorites, total, toggle, externalFavorites, toggleExternal } = useFavorites();
  const { isOffline } = useOfflineStatus();
  const [searchFilter, setSearchFilter] = useState('');
  const [offlineTrackIds, setOfflineTrackIds] = useState<Set<string>>(new Set());

  const getTrack = useCallback(
    (item: FavoriteItem): Track => {
      if (item._kind === 'external') {
        const trackId = item.matched_track_id || item.id;
        return {
          id: trackId,
          file_path: '',
          title: item.title,
          artist: item.artist,
          album: item.album,
          album_artist: null,
          album_type: 'album',
          track_number: null,
          disc_number: null,
          year: item.year ?? null,
          genre: null,
          duration_seconds: item.duration_seconds,
          format: null,
          analysis_version: 0,
        };
      }
      return {
        id: item.id,
        file_path: item.file_path ?? '',
        title: item.title,
        artist: item.artist,
        album: item.album,
        album_artist: item.album_artist ?? null,
        album_type: (item.album_type as Track['album_type']) ?? 'album',
        track_number: item.track_number ?? null,
        disc_number: item.disc_number ?? null,
        year: item.year ?? null,
        genre: item.genre ?? null,
        duration_seconds: item.duration_seconds,
        format: item.format ?? null,
        analysis_version: item.analysis_version ?? 0,
      };
    },
    [],
  );

  // Download state
  const { jobs, startDownload } = useDownloadStore();
  const jobId = 'favorites';
  const downloadJob = jobs.get(jobId);
  const isDownloading = downloadJob?.status === 'downloading' || downloadJob?.status === 'queued';
  const downloadProgress = {
    current: downloadJob ? downloadJob.completedIds.length + (downloadJob.currentProgress > 0 ? 1 : 0) : 0,
    total: downloadJob?.trackIds.length ?? 0,
  };

  // Auto-download setting
  const { data: autoDownloadSetting } = useQuery({
    queryKey: ['favorites-auto-download'],
    queryFn: () => favoritesApi.getAutoDownload(),
    staleTime: 60000,
    retry: isOffline ? false : 3,
  });
  const autoDownloadEnabled = autoDownloadSetting?.enabled ?? false;

  // Check offline status
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
      offlineService.getOfflineTrackIds().then((ids) => {
        setOfflineTrackIds(new Set(ids));
      });
    }
  }, [downloadJob?.status]);

  const favoriteTrackIds = useMemo(() => favorites.map(f => f.id), [favorites]);
  const allTracksOffline = favorites.length > 0 && favorites.every(f => offlineTrackIds.has(f.id));
  const offlineCount = favorites.filter(f => offlineTrackIds.has(f.id)).length;

  // Auto-download new tracks when enabled
  useAutoDownload({
    enabled: autoDownloadEnabled,
    jobId,
    jobType: 'playlist',
    jobName: 'Favorites',
    trackIds: favoriteTrackIds,
  });

  const handleDownloadFavorites = () => {
    if (favorites.length === 0) return;
    const tracksToDownload = favorites.filter(f => !offlineTrackIds.has(f.id));
    if (tracksToDownload.length === 0) return;
    startDownload(jobId, 'playlist', 'Favorites', tracksToDownload.map(f => f.id));
  };

  const searchedFavorites = useMemo(() => {
    if (!searchFilter) return favorites;
    const q = searchFilter.toLowerCase();
    return favorites.filter(t =>
      (t.title?.toLowerCase().includes(q)) ||
      (t.artist?.toLowerCase().includes(q)) ||
      (t.album?.toLowerCase().includes(q))
    );
  }, [favorites, searchFilter]);

  const searchedExternalFavorites = useMemo(() => {
    const extFavs = externalFavorites ?? [];
    if (!searchFilter) return extFavs;
    const q = searchFilter.toLowerCase();
    return extFavs.filter(t =>
      (t.title?.toLowerCase().includes(q)) ||
      (t.artist?.toLowerCase().includes(q)) ||
      (t.album?.toLowerCase().includes(q))
    );
  }, [externalFavorites, searchFilter]);

  const mergedFavorites = useMemo(() => {
    const locals: FavoriteItem[] = searchedFavorites.map(f => ({ ...f, _kind: 'local' as const }));
    const externals: FavoriteItem[] = searchedExternalFavorites.map(f => ({ ...f, _kind: 'external' as const }));
    const all = [...locals, ...externals];
    // Default sort: by favorited_at DESC (interleaved by date)
    all.sort((a, b) => (b.favorited_at || '').localeCompare(a.favorited_at || ''));
    return all;
  }, [searchedFavorites, searchedExternalFavorites]);

  const handlePlay = useCallback((startIndex = 0) => {
    const item = mergedFavorites[startIndex];
    if (!item) return;

    // If clicking on the currently playing track, toggle play/pause
    const trackForItem = getTrack(item);
    if (currentTrack?.id === trackForItem.id) {
      setIsPlaying(!isPlaying);
      return;
    }

    const queueTracks = mergedFavorites.map(t => getTrack(t));
    setQueue(queueTracks, startIndex);
  }, [mergedFavorites, getTrack, currentTrack?.id, isPlaying, setIsPlaying, setQueue]);

  const totalDuration = favorites.reduce(
    (sum, t) => sum + (t.duration_seconds || 0),
    0
  );

  // Render props for PlaylistTrackList
  const renderTitleBadge = useCallback((ctx: TrackRowContext<FavoriteItem>) => {
    if (ctx.item._kind === 'external') {
      const isMatched = ctx.item.is_matched && ctx.item.matched_track_id;
      if (!isMatched) {
        return (
          <>
            <span className="flex-shrink-0 px-1.5 py-0.5 text-[10px] bg-amber-500/20 text-amber-400 rounded">
              Not in library
            </span>
            <StoreSearchLinks
              artist={ctx.item.artist || 'Unknown Artist'}
              title={ctx.item.title || 'Unknown Title'}
              album={ctx.item.album}
            />
          </>
        );
      }
    }
    return null;
  }, []);

  const getRowClassName = useCallback((ctx: TrackRowContext<FavoriteItem>) => {
    if (ctx.item._kind === 'external') {
      const isMatched = ctx.item.is_matched && ctx.item.matched_track_id;
      if (!isMatched) return 'opacity-60';
    }
    return '';
  }, []);

  const renderDesktopTrailing = useCallback((ctx: TrackRowContext<FavoriteItem>) => {
    if (ctx.item._kind === 'external') {
      return (
        <>
          <div className="flex items-center gap-0.5">
            <button
              onClick={(e) => {
                e.stopPropagation();
                toggleExternal(ctx.item.id);
              }}
              className="p-1 text-pink-500 hover:text-pink-400 transition-colors"
              title="Remove from favorites"
            >
              <Heart className="w-4 h-4" fill="currentColor" />
            </button>
            {(ctx.item as ExternalFavoriteTrack).external_links && Object.keys((ctx.item as ExternalFavoriteTrack).external_links).length > 0 && (
              <a
                href={Object.values((ctx.item as ExternalFavoriteTrack).external_links)[0]}
                target="_blank"
                rel="noopener noreferrer"
                onClick={(e) => e.stopPropagation()}
                className="p-1 text-zinc-500 hover:text-green-400 transition-colors"
                title="Open in Spotify"
              >
                <ExternalLink className="w-4 h-4" />
              </a>
            )}
          </div>
          <div className="text-sm text-zinc-500 text-right">
            {formatDuration(ctx.track.duration_seconds)}
          </div>
        </>
      );
    }

    // Local favorite
    return (
      <>
        <button
          onClick={(e) => {
            e.stopPropagation();
            toggle(ctx.item.id);
          }}
          className="p-1 text-pink-500 hover:text-pink-400 transition-colors"
          title="Remove from favorites"
        >
          <Heart className="w-4 h-4" fill="currentColor" />
        </button>
        <div className="text-sm text-zinc-500 text-right">
          {formatDuration(ctx.track.duration_seconds)}
        </div>
      </>
    );
  }, [toggle, toggleExternal]);

  const renderMobileTrailing = useCallback((ctx: TrackRowContext<FavoriteItem>) => {
    const isExternal = ctx.item._kind === 'external';
    return (
      <>
        <button
          onClick={(e) => {
            e.stopPropagation();
            if (isExternal) {
              toggleExternal(ctx.item.id);
            } else {
              toggle(ctx.item.id);
            }
          }}
          className="flex-shrink-0 p-1 text-pink-500 hover:text-pink-400 transition-colors"
        >
          <Heart className="w-4 h-4" fill="currentColor" />
        </button>
        <div className="flex-shrink-0 text-sm text-zinc-500">
          {formatDuration(ctx.track.duration_seconds)}
        </div>
      </>
    );
  }, [toggle, toggleExternal]);

  // Use a stable ID for favorites items since external items have different id namespaces
  const getItemId = useCallback((item: FavoriteItem) => {
    if (item._kind === 'external') return `ext-${item.id}`;
    return item.id;
  }, []);

  return (
    <div className="space-y-4 p-4">
      {/* Header */}
      <div className="space-y-4">
        <button
          onClick={onBack}
          className="p-2 hover:bg-zinc-800 rounded-lg transition-colors -ml-2"
        >
          <ArrowLeft className="w-5 h-5" />
        </button>

        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Heart className="w-5 h-5 text-pink-500" fill="currentColor" />
            <h2 className="text-xl font-bold">Favorites</h2>
          </div>

          <div className="flex items-center gap-4 mt-2 text-sm text-zinc-500">
            <span>{total} tracks</span>
            <span className="flex items-center gap-1">
              <Clock className="w-4 h-4" />
              {Math.floor(totalDuration / 60)} min
            </span>
          </div>
        </div>

        {/* Action buttons */}
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
          <button
            onClick={() => handlePlay(0)}
            disabled={mergedFavorites.length === 0}
            className="flex items-center justify-center gap-2 px-4 py-2 bg-pink-600 hover:bg-pink-500 disabled:opacity-50 disabled:hover:bg-pink-600 rounded-full transition-colors"
          >
            <Play className="w-4 h-4" fill="currentColor" />
            Play
          </button>

          <button
            onClick={handleDownloadFavorites}
            disabled={favorites.length === 0 || isDownloading || allTracksOffline || isOffline}
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
                  {offlineCount > 0 ? `${offlineCount}/${favorites.length}` : 'Download'}
                </span>
              </>
            )}
          </button>

          {/* Auto-download toggle */}
          <button
            onClick={async () => {
              const newValue = !autoDownloadEnabled;
              await favoritesApi.setAutoDownload(newValue);
              queryClient.setQueryData(['favorites-auto-download'], { enabled: newValue });
            }}
            className={`flex items-center justify-center gap-2 px-4 py-2 rounded-full transition-colors ${
              autoDownloadEnabled
                ? 'bg-blue-600 hover:bg-blue-500'
                : 'bg-zinc-700 hover:bg-zinc-600'
            }`}
            title={autoDownloadEnabled ? 'Disable auto-download' : 'Auto-download new favorites'}
          >
            <RotateCw className="w-4 h-4" />
            <span className="text-sm">Auto</span>
          </button>

          {/* External preview toggle */}
          {externalFavorites && externalFavorites.length > 0 && (
            <button
              onClick={() => setPlayExternalPreviews(!playExternalPreviews)}
              className={`flex items-center justify-center gap-2 px-4 py-2 rounded-full transition-colors ${
                playExternalPreviews
                  ? 'bg-amber-600 hover:bg-amber-500'
                  : 'bg-zinc-700 hover:bg-zinc-600'
              }`}
              title={playExternalPreviews ? 'Disable external track previews' : 'Enable external track previews'}
            >
              <ExternalLink className="w-4 h-4" />
              <span className="text-sm">Previews</span>
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
        items={mergedFavorites}
        getTrack={getTrack}
        getItemId={getItemId}
        onPlay={handlePlay}
        renderDesktopTrailing={renderDesktopTrailing}
        renderMobileTrailing={renderMobileTrailing}
        renderTitleBadge={renderTitleBadge}
        getRowClassName={getRowClassName}
        emptyMessage="No favorites yet"
        emptySubMessage="Click the heart icon on any track to add it here"
      />
    </div>
  );
}
