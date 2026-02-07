import { useState, useEffect, useCallback } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import {
  Sparkles, Play, MoreVertical, Trash2, Loader2,
  ChevronDown, ChevronUp, ListMusic, Heart, CloudOff, Download, HardDrive, Gift,
  Clock, X, Save
} from 'lucide-react';
import { playlistsApi, smartPlaylistsApi } from '../../api/client';
import type { Playlist, SmartPlaylist } from '../../api/client';
import { usePlayerStore } from '../../stores/playerStore';
import { useOfflineStatus } from '../../hooks/useOfflineStatus';
import { PlaylistDetail } from './PlaylistDetail';
import { EphemeralPlaylistDetail } from './EphemeralPlaylistDetail';
import { FavoritesDetail } from './FavoritesDetail';
import { DownloadsDetail } from './DownloadsDetail';
import { SmartPlaylistList, SmartPlaylistDetail } from '../SmartPlaylists';
import { NewReleasesView } from '../NewReleases';
import { useFavorites } from '../../hooks/useFavorites';
import { useDownloadedTracks } from '../../hooks/useDownloadedTracks';
import { useEphemeralPlaylistStore, useSaveEphemeralPlaylist } from '../../stores/ephemeralPlaylistStore';
import * as playlistCache from '../../services/playlistCache';

type ViewMode = 'list' | 'detail' | 'favorites' | 'downloads' | 'wishlist' | 'smart-detail' | 'ephemeral-detail';

interface SelectedPlaylist {
  type: 'static' | 'smart';
  id: string;
}

interface Props {
  selectedPlaylistId?: string | null;
  onPlaylistViewed?: () => void;
}

export function PlaylistsView({ selectedPlaylistId, onPlaylistViewed }: Props = {}) {
  const queryClient = useQueryClient();
  const { setQueue, queueSource, isPlaying } = usePlayerStore();
  const { total: favoritesCount } = useFavorites();
  const { total: downloadsCount, totalSizeFormatted: downloadsTotalSize } = useDownloadedTracks();
  const { isOffline } = useOfflineStatus();
  const [searchParams, setSearchParams] = useSearchParams();
  const [cachedPlaylistIds, setCachedPlaylistIds] = useState<Set<string>>(new Set());
  const [usingCachedPlaylists, setUsingCachedPlaylists] = useState(false);
  const [savingPlaylistId, setSavingPlaylistId] = useState<string | null>(null);
  const [selectedEphemeralId, setSelectedEphemeralId] = useState<string | null>(null);

  // Ephemeral playlists (unsaved)
  const ephemeralPlaylists = useEphemeralPlaylistStore((state) => state.playlists);
  const removeEphemeral = useEphemeralPlaylistStore((state) => state.removePlaylist);
  const clearAllEphemeral = useEphemeralPlaylistStore((state) => state.clearAll);
  const saveEphemeralPlaylist = useSaveEphemeralPlaylist();

  // Get playlist ID and view from URL
  const urlPlaylistId = searchParams.get('playlist');
  const urlSmartPlaylistId = searchParams.get('smartPlaylist');
  const urlView = searchParams.get('view');

  // Derive view mode from URL params
  const getViewModeFromUrl = useCallback((): ViewMode => {
    if (urlView === 'favorites') return 'favorites';
    if (urlView === 'downloads') return 'downloads';
    if (urlView === 'wishlist') return 'wishlist';
    if (urlSmartPlaylistId) return 'smart-detail';
    if (urlPlaylistId) return 'detail';
    return 'list';
  }, [urlPlaylistId, urlSmartPlaylistId, urlView]);

  const [viewMode, setViewModeState] = useState<ViewMode>(getViewModeFromUrl);
  const [selectedPlaylist, setSelectedPlaylistState] = useState<SelectedPlaylist | null>(
    urlPlaylistId ? { type: 'static', id: urlPlaylistId } : null
  );
  const [selectedSmartPlaylist, setSelectedSmartPlaylistState] = useState<SmartPlaylist | null>(null);
  const [showAiPlaylists, setShowAiPlaylists] = useState(true);
  const [menuOpen, setMenuOpen] = useState<string | null>(null);

  // Fetch smart playlist from URL if present
  const { data: urlSmartPlaylist } = useQuery({
    queryKey: ['smart-playlist', urlSmartPlaylistId],
    queryFn: () => smartPlaylistsApi.get(urlSmartPlaylistId!),
    enabled: !!urlSmartPlaylistId,
  });

  // Fetch wishlist for count display
  const { data: wishlist, isLoading: wishlistLoading } = useQuery({
    queryKey: ['wishlist'],
    queryFn: () => playlistsApi.getWishlist(),
    retry: isOffline ? false : 3,
  });
  const wishlistCount = wishlist?.tracks?.length ?? 0;

  // Sync URL params to state when they change
  useEffect(() => {
    const newViewMode = getViewModeFromUrl();
    setViewModeState(newViewMode);
    if (urlPlaylistId) {
      setSelectedPlaylistState({ type: 'static', id: urlPlaylistId });
    } else if (urlSmartPlaylistId && urlSmartPlaylist) {
      setSelectedSmartPlaylistState(urlSmartPlaylist);
    } else if (newViewMode === 'list') {
      setSelectedPlaylistState(null);
      setSelectedSmartPlaylistState(null);
    }
  }, [urlPlaylistId, urlSmartPlaylistId, urlSmartPlaylist, urlView, getViewModeFromUrl]);

  // Helper to update URL and state together
  const setViewMode = useCallback((mode: ViewMode) => {
    setViewModeState(mode);
    if (mode === 'favorites') {
      // setSearchParams handles both params and hash update via React Router
      setSearchParams({ view: 'favorites' });
    } else if (mode === 'downloads') {
      setSearchParams({ view: 'downloads' });
    } else if (mode === 'wishlist') {
      setSearchParams({ view: 'wishlist' });
    } else if (mode === 'list') {
      // Clear playlist-related params
      const newParams = new URLSearchParams(searchParams);
      newParams.delete('playlist');
      newParams.delete('smartPlaylist');
      newParams.delete('view');
      setSearchParams(newParams);
    }
  }, [searchParams, setSearchParams]);

  const setSelectedPlaylist = useCallback((playlist: SelectedPlaylist | null) => {
    setSelectedPlaylistState(playlist);
    if (playlist) {
      setSearchParams({ playlist: playlist.id });
      setViewModeState('detail');
    } else {
      const newParams = new URLSearchParams(searchParams);
      newParams.delete('playlist');
      newParams.delete('smartPlaylist');
      newParams.delete('view');
      setSearchParams(newParams);
      setViewModeState('list');
    }
  }, [searchParams, setSearchParams]);

  const setSelectedSmartPlaylist = useCallback((playlist: SmartPlaylist | null) => {
    setSelectedSmartPlaylistState(playlist);
    if (playlist) {
      setSearchParams({ smartPlaylist: playlist.id });
      setViewModeState('smart-detail');
    } else {
      const newParams = new URLSearchParams(searchParams);
      newParams.delete('playlist');
      newParams.delete('smartPlaylist');
      newParams.delete('view');
      setSearchParams(newParams);
      setViewModeState('list');
    }
  }, [searchParams, setSearchParams]);

  // Auto-navigate to playlist when selectedPlaylistId is provided (e.g., from LLM creation)
  useEffect(() => {
    if (selectedPlaylistId) {
      setSelectedPlaylist({ type: 'static', id: selectedPlaylistId });
      setShowAiPlaylists(true);
      onPlaylistViewed?.();
    }
  }, [selectedPlaylistId, onPlaylistViewed, setSelectedPlaylist]);

  // Listen for navigation to specific ephemeral playlist (from LLM chat)
  useEffect(() => {
    const handleShowEphemeral = (e: CustomEvent<{ ephemeralId: string }>) => {
      const { ephemeralId } = e.detail;
      if (ephemeralId) {
        setSelectedEphemeralId(ephemeralId);
        setViewModeState('ephemeral-detail');
      }
    };

    window.addEventListener('show-ephemeral-playlist', handleShowEphemeral as EventListener);
    return () => window.removeEventListener('show-ephemeral-playlist', handleShowEphemeral as EventListener);
  }, []);

  // Load cached playlist IDs to show offline availability indicators
  useEffect(() => {
    const loadCachedIds = async () => {
      const cached = await playlistCache.getCachedPlaylists();
      setCachedPlaylistIds(new Set(cached.map(p => p.id)));
    };
    loadCachedIds();
  }, []);

  // Fetch AI-generated playlists (static playlists) with offline fallback
  const { data: aiPlaylists, isLoading: loadingAi } = useQuery({
    queryKey: ['playlists', 'ai'],
    queryFn: async () => {
      try {
        const data = await playlistsApi.list(true);
        setUsingCachedPlaylists(false);
        return data.filter(p => p.is_auto_generated);
      } catch (error) {
        // If offline, try to load from cache
        if (isOffline) {
          const cached = await playlistCache.getCachedPlaylists();
          const aiCached = cached.filter(p => p.is_auto_generated);
          if (aiCached.length > 0) {
            setUsingCachedPlaylists(true);
            // Convert to Playlist format
            return aiCached.map((p): Playlist => ({
              id: p.id,
              name: p.name,
              description: p.description,
              is_auto_generated: p.is_auto_generated,
              is_wishlist: false,
              generation_prompt: p.generation_prompt,
              track_count: p.track_count,
              local_track_count: p.track_count,
              external_track_count: 0,
              auto_download: false,
              created_at: '',
              updated_at: '',
            }));
          }
        }
        throw error;
      }
    },
    retry: isOffline ? false : 3,
  });

  const deleteMutation = useMutation({
    mutationFn: playlistsApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['playlists'] });
    },
  });

  const playMutation = useMutation({
    mutationFn: async (playlistId: string) => {
      const playlist = await playlistsApi.get(playlistId);
      return { tracks: playlist.tracks, playlistId };
    },
    onSuccess: ({ tracks, playlistId }) => {
      if (tracks.length > 0) {
        const queueTracks = tracks.map(t => ({
          id: t.id,
          file_path: '',
          title: t.title || 'Unknown',
          artist: t.artist || 'Unknown',
          album: t.album || null,
          album_artist: null,
          album_type: 'album' as const,
          track_number: null,
          disc_number: null,
          year: null,
          genre: null,
          duration_seconds: t.duration_seconds || null,
          format: null,
          analysis_version: 0,
        }));
        setQueue(queueTracks, 0, { type: 'playlist', id: playlistId });
      }
    },
  });

  const handleSelectPlaylist = (playlist: Playlist) => {
    setSelectedPlaylist({ type: 'static', id: playlist.id });
  };

  const handleSelectSmartPlaylist = (playlist: SmartPlaylist) => {
    setSelectedSmartPlaylist(playlist);
  };

  const handleBack = () => {
    setSelectedPlaylist(null);
  };

  const handleDelete = (id: string) => {
    if (confirm('Delete this playlist?')) {
      deleteMutation.mutate(id);
    }
    setMenuOpen(null);
  };

  const handlePlay = (id: string) => {
    playMutation.mutate(id);
  };

  // Handle saving an ephemeral playlist
  const handleSaveEphemeral = async (id: string) => {
    setSavingPlaylistId(id);
    try {
      const savedId = await saveEphemeralPlaylist(id);
      // Navigate to the saved playlist
      setSelectedPlaylist({ type: 'static', id: savedId });
    } catch (error) {
      console.error('Failed to save playlist:', error);
    } finally {
      setSavingPlaylistId(null);
    }
  };

  // Play an ephemeral playlist (queue the tracks)
  const handlePlayEphemeral = (playlist: typeof ephemeralPlaylists[0]) => {
    if (playlist.tracks.length > 0) {
      const queueTracks = playlist.tracks.map((t) => ({
        id: t.id,
        file_path: '',
        title: t.title || 'Unknown',
        artist: t.artist || 'Unknown',
        album: t.album || null,
        album_artist: null,
        album_type: 'album' as const,
        track_number: null,
        disc_number: null,
        year: null,
        genre: null,
        duration_seconds: t.duration_seconds || null,
        format: null,
        analysis_version: 0,
      }));
      setQueue(queueTracks, 0, { type: 'ephemeral', id: playlist.id });
    }
  };

  // Show favorites view
  if (viewMode === 'favorites') {
    return (
      <FavoritesDetail onBack={handleBack} />
    );
  }

  // Show downloads view
  if (viewMode === 'downloads') {
    return (
      <DownloadsDetail onBack={handleBack} />
    );
  }

  // Show wishlist view (reuse PlaylistDetail with wishlist ID)
  if (viewMode === 'wishlist') {
    if (wishlistLoading || !wishlist?.id) {
      return (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-6 h-6 animate-spin text-zinc-400" />
        </div>
      );
    }
    return (
      <PlaylistDetail
        playlistId={wishlist.id}
        onBack={handleBack}
      />
    );
  }

  // Show smart playlist detail view
  if (viewMode === 'smart-detail' && selectedSmartPlaylist) {
    return (
      <SmartPlaylistDetail
        playlist={selectedSmartPlaylist}
        onBack={() => {
          setSelectedSmartPlaylist(null);
        }}
      />
    );
  }

  // Show ephemeral playlist detail view
  const selectedEphemeral = selectedEphemeralId
    ? ephemeralPlaylists.find((p) => p.id === selectedEphemeralId)
    : null;
  if (viewMode === 'ephemeral-detail' && selectedEphemeral) {
    return (
      <EphemeralPlaylistDetail
        playlist={selectedEphemeral}
        onBack={() => {
          setSelectedEphemeralId(null);
          setViewMode('list');
        }}
        onSave={async () => {
          setSavingPlaylistId(selectedEphemeralId);
          try {
            const savedId = await saveEphemeralPlaylist(selectedEphemeralId!);
            setSelectedEphemeralId(null);
            // Navigate to the saved playlist
            setSelectedPlaylist({ type: 'static', id: savedId });
          } catch (error) {
            console.error('Failed to save playlist:', error);
          } finally {
            setSavingPlaylistId(null);
          }
        }}
        onDelete={() => {
          removeEphemeral(selectedEphemeralId!);
          setSelectedEphemeralId(null);
          setViewMode('list');
        }}
        isSaving={savingPlaylistId === selectedEphemeralId}
      />
    );
  }

  // Show detail view if a playlist is selected
  if (viewMode === 'detail' && selectedPlaylist?.type === 'static') {
    return (
      <PlaylistDetail
        playlistId={selectedPlaylist.id}
        onBack={handleBack}
      />
    );
  }

  const hasAiPlaylists = aiPlaylists && aiPlaylists.length > 0;

  return (
    <div className="space-y-6">
      {/* Favorites Section - Always at top */}
      <button
        onClick={() => setViewMode('favorites')}
        className="w-full flex items-center gap-3 p-3 bg-gradient-to-r from-pink-500/10 to-purple-500/10 hover:from-pink-500/20 hover:to-purple-500/20 rounded-lg border border-pink-500/20 transition-colors"
      >
        <div className="p-2 rounded-full bg-pink-500/20">
          <Heart className="w-5 h-5 text-pink-500" fill="currentColor" />
        </div>
        <div className="flex-1 text-left">
          <div className="font-semibold">Favorites</div>
          <div className="text-sm text-zinc-400">{favoritesCount} tracks</div>
        </div>
      </button>

      {/* Downloads Section */}
      <button
        onClick={() => setViewMode('downloads')}
        className="w-full flex items-center gap-3 p-3 bg-gradient-to-r from-green-500/10 to-emerald-500/10 hover:from-green-500/20 hover:to-emerald-500/20 rounded-lg border border-green-500/20 transition-colors"
      >
        <div className="p-2 rounded-full bg-green-500/20">
          <Download className="w-5 h-5 text-green-500" />
        </div>
        <div className="flex-1 text-left">
          <div className="font-semibold">Downloads</div>
          <div className="text-sm text-zinc-400 flex items-center gap-2">
            <span>{downloadsCount} tracks</span>
            {downloadsCount > 0 && (
              <>
                <span className="text-zinc-600">•</span>
                <span className="flex items-center gap-1">
                  <HardDrive className="w-3 h-3" />
                  {downloadsTotalSize}
                </span>
              </>
            )}
          </div>
        </div>
      </button>

      {/* Wishlist Section */}
      <button
        onClick={() => setViewMode('wishlist')}
        className="w-full flex items-center gap-3 p-3 bg-gradient-to-r from-purple-500/10 to-indigo-500/10 hover:from-purple-500/20 hover:to-indigo-500/20 rounded-lg border border-purple-500/20 transition-colors"
      >
        <div className="p-2 rounded-full bg-purple-500/20">
          <Gift className="w-5 h-5 text-purple-500" />
        </div>
        <div className="flex-1 text-left">
          <div className="font-semibold">Wishlist</div>
          <div className="text-sm text-zinc-400">
            {wishlistCount} {wishlistCount === 1 ? 'item' : 'items'} to acquire
          </div>
        </div>
      </button>

      {/* Unsaved Playlists Section - ephemeral, lost on refresh */}
      {ephemeralPlaylists.length > 0 && (
        <div>
          <div className="flex items-center justify-between px-2 py-2">
            <div className="flex items-center gap-2">
              <Clock className="w-5 h-5 text-amber-400" />
              <span className="font-semibold">Unsaved</span>
              <span className="text-xs text-zinc-500">(lost on refresh)</span>
            </div>
            <button
              onClick={clearAllEphemeral}
              className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
            >
              Clear All
            </button>
          </div>

          <div className="mt-2 space-y-2">
            {ephemeralPlaylists.map((playlist) => {
              const isNowPlaying = queueSource?.type === 'ephemeral' && queueSource?.id === playlist.id;
              const isSaving = savingPlaylistId === playlist.id;
              return (
                <div
                  key={playlist.id}
                  className={`group flex items-center gap-3 p-3 rounded-lg border border-dashed transition-colors ${
                    isNowPlaying
                      ? 'bg-green-900/20 hover:bg-green-900/30 border-green-500/30'
                      : 'bg-zinc-800/30 hover:bg-zinc-800/50 border-zinc-700'
                  }`}
                >
                  {/* Now playing indicator or Play button */}
                  {isNowPlaying && isPlaying ? (
                    <div className="p-2 bg-green-600 rounded-full flex items-center justify-center">
                      <div className="flex items-center gap-0.5">
                        <div className="w-0.5 h-3 bg-white animate-pulse" />
                        <div className="w-0.5 h-3 bg-white animate-pulse [animation-delay:0.2s]" />
                        <div className="w-0.5 h-3 bg-white animate-pulse [animation-delay:0.4s]" />
                      </div>
                    </div>
                  ) : (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handlePlayEphemeral(playlist);
                      }}
                      className={`p-2 rounded-full transition-opacity ${
                        isNowPlaying
                          ? 'bg-green-600 hover:bg-green-500 opacity-100'
                          : 'bg-amber-600 hover:bg-amber-500 opacity-100 sm:opacity-0 sm:group-hover:opacity-100'
                      }`}
                    >
                      <Play className="w-4 h-4" fill="currentColor" />
                    </button>
                  )}

                  {/* Info - clickable to open detail */}
                  <div
                    className="flex-1 min-w-0 cursor-pointer"
                    onClick={() => {
                      setSelectedEphemeralId(playlist.id);
                      setViewModeState('ephemeral-detail');
                    }}
                  >
                    <div className={`font-medium truncate ${isNowPlaying ? 'text-green-400' : ''}`}>
                      {playlist.name}
                    </div>
                    <div className="text-sm text-zinc-400 flex items-center gap-2">
                      <span>{playlist.tracks.length} tracks</span>
                      {playlist.generationPrompt && (
                        <>
                          <span className="text-zinc-600">|</span>
                          <span className="truncate max-w-xs text-amber-400/70">
                            "{playlist.generationPrompt}"
                          </span>
                        </>
                      )}
                    </div>
                  </div>

                  {/* Actions */}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handleSaveEphemeral(playlist.id);
                    }}
                    disabled={isSaving || isOffline}
                    className="px-3 py-1.5 text-sm bg-green-600 hover:bg-green-500 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5"
                    title="Save playlist"
                  >
                    {isSaving ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <Save className="w-3.5 h-3.5" />
                    )}
                    <span className="hidden sm:inline">Save</span>
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      removeEphemeral(playlist.id);
                    }}
                    className="p-1.5 text-zinc-400 hover:text-white hover:bg-zinc-700 rounded-lg transition-colors"
                    title="Dismiss"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* AI-Generated Playlists Section */}
      {hasAiPlaylists && (
        <div>
          <button
            onClick={() => setShowAiPlaylists(!showAiPlaylists)}
            className="w-full flex items-center justify-between px-2 py-2 hover:bg-zinc-800/50 rounded-lg transition-colors"
          >
            <div className="flex items-center gap-2">
              <Sparkles className="w-5 h-5 text-purple-400" />
              <span className="font-semibold">AI Playlists</span>
              <span className="text-sm text-zinc-500">({aiPlaylists.length})</span>
              {usingCachedPlaylists && (
                <span className="flex items-center gap-1 px-2 py-0.5 text-xs bg-amber-500/20 text-amber-400 rounded-full">
                  <CloudOff className="w-3 h-3" />
                  Offline
                </span>
              )}
            </div>
            {showAiPlaylists ? (
              <ChevronUp className="w-5 h-5 text-zinc-400" />
            ) : (
              <ChevronDown className="w-5 h-5 text-zinc-400" />
            )}
          </button>

          {showAiPlaylists && (
            <div className="mt-2 space-y-2">
              {loadingAi ? (
                <div className="flex items-center justify-center py-4">
                  <Loader2 className="w-5 h-5 animate-spin text-zinc-400" />
                </div>
              ) : (
                aiPlaylists.map((playlist) => {
                  const isNowPlaying = queueSource?.type === 'playlist' && queueSource?.id === playlist.id;
                  return (
                  <div
                    key={playlist.id}
                    className={`group flex items-center gap-3 p-3 rounded-lg transition-colors ${
                      isNowPlaying
                        ? 'bg-green-900/20 hover:bg-green-900/30 ring-1 ring-green-500/30'
                        : 'bg-zinc-800/50 hover:bg-zinc-800'
                    }`}
                  >
                    {/* Now playing indicator or Play button */}
                    {isNowPlaying && isPlaying ? (
                      <div className="p-2 bg-green-600 rounded-full flex items-center justify-center">
                        <div className="flex items-center gap-0.5">
                          <div className="w-0.5 h-3 bg-white animate-pulse" />
                          <div className="w-0.5 h-3 bg-white animate-pulse [animation-delay:0.2s]" />
                          <div className="w-0.5 h-3 bg-white animate-pulse [animation-delay:0.4s]" />
                        </div>
                      </div>
                    ) : (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handlePlay(playlist.id);
                        }}
                        disabled={playMutation.isPending}
                        className={`p-2 rounded-full transition-opacity disabled:opacity-50 ${
                          isNowPlaying
                            ? 'bg-green-600 hover:bg-green-500 opacity-100'
                            : 'bg-purple-600 hover:bg-purple-500 opacity-100 sm:opacity-0 sm:group-hover:opacity-100'
                        }`}
                      >
                        {playMutation.isPending ? (
                          <Loader2 className="w-4 h-4 animate-spin" />
                        ) : (
                          <Play className="w-4 h-4" fill="currentColor" />
                        )}
                      </button>
                    )}

                    {/* Info */}
                    <div
                      className="flex-1 min-w-0 cursor-pointer"
                      onClick={() => handleSelectPlaylist(playlist)}
                    >
                      <div className={`font-medium truncate flex items-center gap-2 ${isNowPlaying ? 'text-green-400' : ''}`}>
                        {playlist.name}
                        {cachedPlaylistIds.has(playlist.id) && (
                          <span title="Available offline">
                            <CloudOff className="w-3.5 h-3.5 text-green-500" />
                          </span>
                        )}
                      </div>
                      <div className="text-sm text-zinc-400 flex items-center gap-2">
                        <span>{playlist.track_count} tracks</span>
                        {playlist.generation_prompt && (
                          <>
                            <span className="text-zinc-600">|</span>
                            <span className="truncate max-w-xs text-purple-400/70">
                              "{playlist.generation_prompt}"
                            </span>
                          </>
                        )}
                      </div>
                    </div>

                    {/* Menu */}
                    <div className="relative">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setMenuOpen(menuOpen === playlist.id ? null : playlist.id);
                        }}
                        className="p-1 hover:bg-zinc-700 rounded-md opacity-100 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity"
                      >
                        <MoreVertical className="w-5 h-5 text-zinc-400" />
                      </button>

                      {menuOpen === playlist.id && (
                        <>
                          <div
                            className="fixed inset-0 z-10"
                            onClick={() => setMenuOpen(null)}
                          />
                          <div className="absolute right-0 top-8 w-32 bg-zinc-800 border border-zinc-700 rounded-lg shadow-xl z-20 py-1">
                            <button
                              onClick={() => handleDelete(playlist.id)}
                              disabled={isOffline}
                              className="w-full px-3 py-2 text-left text-sm hover:bg-zinc-700 flex items-center gap-2 text-red-400 disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                              <Trash2 className="w-4 h-4" />
                              Delete
                            </button>
                          </div>
                        </>
                      )}
                    </div>
                  </div>
                  );
                })
              )}
            </div>
          )}
        </div>
      )}

      {/* New Releases Section */}
      <NewReleasesView />

      {/* Smart Playlists Section */}
      <SmartPlaylistList onSelectPlaylist={handleSelectSmartPlaylist} />

      {/* Empty state */}
      {!hasAiPlaylists && !loadingAi && (
        <div className="text-center py-8 text-zinc-500 border-t border-zinc-800 mt-4 pt-8">
          <ListMusic className="w-12 h-12 mx-auto mb-3 opacity-50" />
          <p>No AI-generated playlists yet</p>
          <p className="text-sm mt-1">Ask Familiar to create a playlist for you</p>
        </div>
      )}
    </div>
  );
}
