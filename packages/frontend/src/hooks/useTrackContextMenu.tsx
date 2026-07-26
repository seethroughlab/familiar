import { useState, useCallback, useMemo } from 'react';
import { usePlayerStore } from '../stores/playerStore';
import { useSelectionStore } from '../stores/selectionStore';
import { useAppNavigation } from './useAppNavigation';
import { useFavorites } from './useFavorites';
import { TrackContextMenu } from '../components/Library/TrackContextMenu';
import type { ContextMenuState } from '../components/Library/types';
import { initialContextMenuState } from '../components/Library/types';
import { useUIStore } from '../stores/uiStore';
import { downloadApi } from '../api';
import { showLoading, showError } from '../stores/toastStore';
import { toast } from 'sonner';
import type { Track } from '../types';

interface UseTrackContextMenuOptions {
  /** Called to play the context menu track. Receives the track. */
  onPlay?: (track: Track) => void;
  /** Return true if the track is currently selected (for multi-select views). */
  isSelected?: (trackId: string) => boolean;
  /** Number of currently selected tracks (shows bulk actions when > 1). */
  selectedCount?: number;
  /** Set of currently selected track IDs — derives isSelected/selectedCount and handles selectAll in default onEditMetadata. */
  selectedTrackIds?: Set<string>;
  /** Called before navigation (e.g. FullPlayer calls onClose()). */
  beforeNavigate?: () => void;
  /** Toggle selection for a track. */
  onToggleSelect?: (track: Track) => void;
  /** Clear selection. */
  onClearSelection?: () => void;
  /** Override queue behavior. */
  onQueue?: (track: Track) => void;
  /** Override Go to Artist. Pass () => {} for no-op when already on artist page. */
  onGoToArtist?: (track: Track) => void;
  /** Override Go to Album. Pass () => {} for no-op when already on album page. */
  onGoToAlbum?: (track: Track) => void;
  /** Edit metadata handler — if omitted, uses default selectionStore behavior (with selectAll when selectedTrackIds provided). */
  onEditMetadata?: (track: Track) => void;
  /** Extra handler: explore similar artists (TrackListBrowser). */
  onExploreSimilarArtists?: (track: Track) => void;
  /** Extra handler: remove from downloads (DownloadsDetail). */
  onRemoveFromDownloads?: (track: Track) => void;
  /** Extra handler: remove from playlist (PlaylistDetail). */
  onRemoveFromPlaylist?: (track: Track) => void;
  /** Bulk play selected handler. */
  onPlaySelected?: () => void;
  /** Bulk add selected to playlist. */
  onAddSelectedToPlaylist?: () => void;
  /** Bulk download selected tracks for offline. */
  onDownloadSelectedTracks?: () => void;
  /** Bulk download selected track analyses. */
  onDownloadSelectedAnalyses?: () => void;
  /** Resolve selected track IDs to Track objects. Required for default onPlaySelected. */
  resolveSelectedTracks?: (ids: Set<string>) => Track[];
}

export function useTrackContextMenu(options: UseTrackContextMenuOptions = {}) {
  const [contextMenu, setContextMenu] = useState<ContextMenuState>(initialContextMenuState);
  const addToQueue = usePlayerStore((s) => s.addToQueue);
  const setQueue = usePlayerStore((s) => s.setQueue);
  const { navigateToArtist, navigateToAlbumDetail } = useAppNavigation();
  const { isFavorite, toggle: toggleFavorite } = useFavorites();

  const handleContextMenu = useCallback((track: Track, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setContextMenu({ isOpen: true, track, position: { x: e.clientX, y: e.clientY } });
  }, []);

  const closeContextMenu = useCallback(() => {
    setContextMenu(initialContextMenuState);
  }, []);

  // Open context menu programmatically (for long-press on mobile)
  const openContextMenu = useCallback((track: Track, position: { x: number; y: number }) => {
    setContextMenu({ isOpen: true, track, position });
  }, []);

  const contextMenuElement = useMemo(() => {
    if (!contextMenu.isOpen || !contextMenu.track) return null;

    const track = contextMenu.track;
    const sel = options.selectedTrackIds;
    const effectiveIsSelected = options.isSelected
      ? options.isSelected(track.id)
      : sel ? sel.has(track.id) : false;
    const effectiveSelectedCount = options.selectedCount ?? sel?.size;

    // Default bulk action callbacks (used when caller doesn't override)
    const defaultPlaySelected = sel && options.resolveSelectedTracks && options.onClearSelection
      ? () => {
          const tracks = options.resolveSelectedTracks!(sel);
          if (tracks.length > 0) {
            setQueue(tracks, 0);
            options.onClearSelection!();
          }
        }
      : undefined;

    const defaultAddSelectedToPlaylist = sel && options.resolveSelectedTracks
      ? () => {
          const tracks = options.resolveSelectedTracks!(sel);
          if (tracks.length > 0) {
            useUIStore.getState().openPlaylistPicker(tracks.map(t => t.id));
          }
        }
      : undefined;

    const defaultDownloadSelectedTracks = sel && options.resolveSelectedTracks
      ? async () => {
          const tracks = options.resolveSelectedTracks!(sel);
          if (tracks.length === 0) return;
          const trackIds = tracks.map(t => t.id);
          try {
            await downloadApi.tracks(trackIds, `${trackIds.length} Selected Tracks`);
          } catch {
            showError('Failed to download tracks');
          }
        }
      : undefined;

    const defaultDownloadSelectedAnalyses = sel && options.resolveSelectedTracks
      ? async () => {
          const tracks = options.resolveSelectedTracks!(sel);
          if (tracks.length === 0) return;
          const trackIds = tracks.map(t => t.id);
          const toastId = showLoading(`Preparing ${trackIds.length} analyses...`);
          try {
            await downloadApi.analysesZip(trackIds, `${trackIds.length} Track Analyses`, (done, total) => {
              toast.loading(`Analyzing tracks... ${done}/${total}`, { id: toastId });
            });
            toast.success('Analyses downloaded!', { id: toastId });
          } catch {
            toast.error('Failed to download analyses', { id: toastId });
          }
        }
      : undefined;

    return (
      <TrackContextMenu
        track={track}
        position={contextMenu.position}
        isSelected={effectiveIsSelected}
        selectedCount={effectiveSelectedCount}
        onClose={closeContextMenu}
        onPlay={() => {
          options.onPlay?.(track);
        }}
        onQueue={() => {
          if (options.onQueue) {
            options.onQueue(track);
          } else {
            addToQueue(track);
          }
        }}
        onGoToArtist={() => {
          if (options.onGoToArtist) {
            options.onGoToArtist(track);
          } else if (track.artist) {
            options.beforeNavigate?.();
            navigateToArtist(track.artist);
          }
        }}
        onGoToAlbum={() => {
          if (options.onGoToAlbum) {
            options.onGoToAlbum(track);
          } else {
            const albumArtist = track.album_artist || track.artist;
            if (albumArtist && track.album) {
              options.beforeNavigate?.();
              navigateToAlbumDetail(albumArtist, track.album);
            }
          }
        }}
        onExploreSimilarArtists={
          options.onExploreSimilarArtists
            ? () => options.onExploreSimilarArtists!(track)
            : undefined
        }
        onToggleSelect={() => {
          options.onToggleSelect?.(track);
        }}
        onAddToPlaylist={() => {
          useUIStore.getState().openPlaylistPicker([track.id]);
        }}
        onMakePlaylist={() => {
          const message = `Make me a playlist based on "${track.title || 'this track'}" by ${track.artist || 'Unknown Artist'}`;
          options.beforeNavigate?.();
          useUIStore.getState().triggerChat(message);
        }}
        onEditMetadata={() => {
          if (options.onEditMetadata) {
            options.onEditMetadata(track);
          } else {
            if (sel && sel.size > 1 && sel.has(track.id)) {
              useSelectionStore.getState().selectAll(Array.from(sel));
            }
            useSelectionStore.getState().setEditingTrackId(track.id);
          }
        }}
        onRemoveFromDownloads={
          options.onRemoveFromDownloads
            ? () => options.onRemoveFromDownloads!(track)
            : undefined
        }
        onRemoveFromPlaylist={
          options.onRemoveFromPlaylist
            ? () => options.onRemoveFromPlaylist!(track)
            : undefined
        }
        isFavorite={isFavorite(track.id)}
        onToggleFavorite={() => {
          toggleFavorite(track.id);
        }}
        onPlaySelected={options.onPlaySelected ?? defaultPlaySelected}
        onAddSelectedToPlaylist={options.onAddSelectedToPlaylist ?? defaultAddSelectedToPlaylist}
        onDownloadSelectedTracks={options.onDownloadSelectedTracks ?? defaultDownloadSelectedTracks}
        onDownloadSelectedAnalyses={options.onDownloadSelectedAnalyses ?? defaultDownloadSelectedAnalyses}
        onClearSelection={options.onClearSelection}
      />
    );
  }, [
    contextMenu, options, closeContextMenu, addToQueue, setQueue,
    navigateToArtist, navigateToAlbumDetail, isFavorite, toggleFavorite,
  ]);

  return {
    contextMenu,
    handleContextMenu,
    closeContextMenu,
    openContextMenu,
    contextMenuElement,
  };
}
