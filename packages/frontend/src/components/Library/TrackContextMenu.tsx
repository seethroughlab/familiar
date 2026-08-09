/**
 * Context menu for track actions.
 *
 * Shows on right-click with options like Play, Queue, Go to Artist, etc.
 */
import { useAnalysis } from '../../hooks/useAnalysis';
import {
  Play,
  ListPlus,
  User,
  Disc,
  CheckSquare,
  Square,
  Sparkles,
  Edit3,
  Map,
  Trash2,
  X,
  Heart,
  FileText,
  Download,
  Copy,
} from 'lucide-react';
import { toast } from 'sonner';
import type { Track } from '../../types';
import { ContextMenuContainer, MenuItem, MenuDivider, MenuHeader } from '../ui/ContextMenu';

interface TrackContextMenuProps {
  track: Track;
  position: { x: number; y: number };
  isSelected: boolean;
  onClose: () => void;
  onPlay: () => void;
  onQueue: () => void;
  onGoToArtist: () => void;
  onGoToAlbum: () => void;
  onExploreSimilarArtists?: () => void;
  onToggleSelect: () => void;
  onAddToPlaylist: () => void;
  onMakePlaylist: () => void;
  onEditMetadata?: () => void;
  onRemoveFromDownloads?: () => void;
  onRemoveFromPlaylist?: () => void;
  // Favorite toggle
  isFavorite?: boolean;
  onToggleFavorite?: () => void;
  // Bulk selection props (for mobile long-press)
  selectedCount?: number;
  onPlaySelected?: () => void;
  onAddSelectedToPlaylist?: () => void;
  onDownloadSelectedTracks?: () => void;
  onDownloadSelectedAnalyses?: () => void;
  onClearSelection?: () => void;
}

export function TrackContextMenu({
  track,
  position,
  isSelected,
  onClose,
  onPlay,
  onQueue,
  onGoToArtist,
  onGoToAlbum,
  onExploreSimilarArtists,
  onToggleSelect,
  onAddToPlaylist,
  onMakePlaylist,
  onEditMetadata,
  onRemoveFromDownloads,
  onRemoveFromPlaylist,
  isFavorite,
  onToggleFavorite,
  selectedCount = 0,
  onPlaySelected,
  onAddSelectedToPlaylist,
  onDownloadSelectedTracks,
  onDownloadSelectedAnalyses,
  onClearSelection,
}: TrackContextMenuProps) {
  const { downloadAnalysis } = useAnalysis();

  const handleAction = (action: () => void) => {
    action();
    onClose();
  };

  const showBulkActions = selectedCount > 1;

  return (
    <ContextMenuContainer position={position} onClose={onClose}>
      {/* Bulk actions section (shown when multiple tracks selected) */}
      {showBulkActions && (
        <>
          <div className="px-3 py-2 border-b border-zinc-700 bg-purple-900/30">
            <div className="text-sm font-medium text-purple-300">
              {selectedCount} tracks selected
            </div>
          </div>
          {onPlaySelected && (
            <MenuItem
              icon={<Play className="w-4 h-4" />}
              label={`Play ${selectedCount} selected`}
              onClick={() => handleAction(onPlaySelected)}
            />
          )}
          {onAddSelectedToPlaylist && (
            <MenuItem
              icon={<ListPlus className="w-4 h-4" />}
              label={`Add ${selectedCount} to playlist...`}
              onClick={() => handleAction(onAddSelectedToPlaylist)}
            />
          )}
          {onDownloadSelectedTracks && (
            <MenuItem
              icon={<Download className="w-4 h-4" />}
              label={`Download ${selectedCount} tracks as ZIP`}
              onClick={() => handleAction(onDownloadSelectedTracks)}
            />
          )}
          {onDownloadSelectedAnalyses && (
            <MenuItem
              icon={<FileText className="w-4 h-4" />}
              label={`Download ${selectedCount} analyses as ZIP`}
              onClick={() => handleAction(onDownloadSelectedAnalyses)}
            />
          )}
          {onClearSelection && (
            <MenuItem
              icon={<X className="w-4 h-4" />}
              label="Clear selection"
              onClick={() => handleAction(onClearSelection)}
            />
          )}
          <MenuDivider />
        </>
      )}

      {/* Track info header */}
      <MenuHeader
        title={track.title || 'Unknown'}
        subtitle={track.artist || 'Unknown Artist'}
      />

      {/* Playback actions */}
      <MenuItem
        icon={<Play className="w-4 h-4" />}
        label="Play"
        onClick={() => handleAction(onPlay)}
      />
      <MenuItem
        icon={<ListPlus className="w-4 h-4" />}
        label="Add to Queue"
        onClick={() => handleAction(onQueue)}
      />

      <MenuDivider />

      {/* Navigation actions */}
      <MenuItem
        icon={<User className="w-4 h-4" />}
        label="Go to Artist"
        onClick={() => handleAction(onGoToArtist)}
        disabled={!track.artist}
      />
      <MenuItem
        icon={<Disc className="w-4 h-4" />}
        label="Go to Album"
        onClick={() => handleAction(onGoToAlbum)}
        disabled={!track.album}
      />
      {onExploreSimilarArtists && (
        <MenuItem
          icon={<Map className="w-4 h-4" />}
          label="Explore Similar Artists"
          onClick={() => handleAction(onExploreSimilarArtists)}
          disabled={!track.artist}
        />
      )}

      <MenuDivider />

      {/* Selection */}
      <MenuItem
        icon={isSelected ? <CheckSquare className="w-4 h-4" /> : <Square className="w-4 h-4" />}
        label={isSelected ? 'Deselect' : 'Select'}
        onClick={() => handleAction(onToggleSelect)}
      />

      {/* Favorite */}
      {onToggleFavorite && (
        <MenuItem
          icon={<Heart className="w-4 h-4" fill={isFavorite ? 'currentColor' : 'none'} />}
          label={isFavorite ? 'Remove from Favorites' : 'Add to Favorites'}
          onClick={() => handleAction(onToggleFavorite)}
          iconClassName={isFavorite ? 'text-pink-500' : 'text-zinc-400'}
        />
      )}

      {/* Edit Metadata */}
      {onEditMetadata && (
        <MenuItem
          icon={<Edit3 className="w-4 h-4" />}
          label="Edit Metadata..."
          onClick={() => handleAction(onEditMetadata)}
        />
      )}

      {/* Download Track Analysis */}
      <MenuItem
        icon={<FileText className="w-4 h-4" />}
        label="Download Track Analysis"
        onClick={() => handleAction(() => downloadAnalysis(track))}
      />

      {/* Copy Track ID */}
      <MenuItem
        icon={<Copy className="w-4 h-4" />}
        label="Copy Track ID"
        onClick={() => handleAction(() => {
          navigator.clipboard.writeText(track.id);
          toast.success('Track ID copied to clipboard');
        })}
      />

      {/* Remove from Downloads */}
      {onRemoveFromDownloads && (
        <MenuItem
          icon={<Trash2 className="w-4 h-4" />}
          label="Remove from Downloads"
          onClick={() => handleAction(onRemoveFromDownloads)}
        />
      )}

      {/* Remove from Playlist */}
      {onRemoveFromPlaylist && (
        <MenuItem
          icon={<Trash2 className="w-4 h-4" />}
          label="Remove from Playlist"
          onClick={() => handleAction(onRemoveFromPlaylist)}
        />
      )}

      {/* Playlist */}
      <MenuItem
        icon={<ListPlus className="w-4 h-4" />}
        label="Add to Playlist..."
        onClick={() => handleAction(onAddToPlaylist)}
      />


      <MenuDivider />

      {/*
        **No longer gated on a chat provider** (ADR-0048). This used to open the chat panel, so it
        was correctly hidden without one; it now posts a structured seed to
        `POST /playlists/generate`, which is scored from the library's own analysis and works on a
        server with no model at all. Leaving the gate would have hidden the button precisely where
        the ADR promises it still works — a mounted destination with no affordance, which is the
        `#70`/`#74`/`#76` defect inverted.
      */}
      <MenuItem
        icon={<Sparkles className="w-4 h-4" />}
        label="Make Playlist From This..."
        onClick={() => handleAction(onMakePlaylist)}
      />
    </ContextMenuContainer>
  );
}
