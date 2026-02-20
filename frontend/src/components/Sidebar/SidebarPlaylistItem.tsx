/**
 * SidebarPlaylistItem - Playlist link in the sidebar with drag-and-drop support.
 *
 * Accepts `application/track-id` drops to add tracks to the playlist.
 * Shows visual feedback (green ring) when a track is dragged over.
 */
import { useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { ListMusic } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { playlistsApi } from '../../api/client';
import { useSelectionStore } from '../../stores/selectionStore';
import { showSuccess, showError } from '../../stores/toastStore';

interface Props {
  id: string;
  name: string;
  trackCount: number;
  to: string;
  isActive: boolean;
  activeClass: string;
  textClass: string;
  hoverClass: string;
  countClass: string;
  onContextMenu?: (e: React.MouseEvent) => void;
}

export function SidebarPlaylistItem({
  id,
  name,
  trackCount,
  to,
  isActive,
  activeClass,
  textClass,
  hoverClass,
  countClass,
  onContextMenu,
}: Props) {
  const [isDragOver, setIsDragOver] = useState(false);
  const queryClient = useQueryClient();
  const selectedIds = useSelectionStore((s) => s.selectedIds);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    if (e.dataTransfer.types.includes('application/track-id')) {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'copy';
      setIsDragOver(true);
    }
  }, []);

  const handleDragLeave = useCallback(() => {
    setIsDragOver(false);
  }, []);

  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);

    const trackId = e.dataTransfer.getData('application/track-id');
    if (!trackId) return;

    // If the dropped track is part of a multi-selection, add all selected tracks
    const trackIds = selectedIds.has(trackId) && selectedIds.size > 1
      ? Array.from(selectedIds)
      : [trackId];

    try {
      await playlistsApi.addTracks(id, trackIds);
      queryClient.invalidateQueries({ queryKey: ['playlists'] });
      queryClient.invalidateQueries({ queryKey: ['playlist', id] });
      const countLabel = trackIds.length === 1 ? '1 track' : `${trackIds.length} tracks`;
      showSuccess(`Added ${countLabel} to "${name}"`);
    } catch {
      showError(`Failed to add to "${name}"`);
    }
  }, [id, name, selectedIds, queryClient]);

  return (
    <div onContextMenu={onContextMenu}>
      <Link
        to={to}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={`flex items-center gap-3 px-2 py-1.5 rounded-lg text-sm transition-colors ${
          isDragOver
            ? 'ring-2 ring-green-500 bg-green-500/10'
            : isActive
              ? activeClass
              : `${textClass} ${hoverClass}`
        }`}
      >
        <ListMusic className="w-4 h-4 flex-shrink-0" />
        <span className="truncate flex-1">{name}</span>
        <span className={`text-xs ${countClass}`}>
          {trackCount}
        </span>
      </Link>
    </div>
  );
}
