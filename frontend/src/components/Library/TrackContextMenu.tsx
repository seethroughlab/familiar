/**
 * Context menu for track actions.
 *
 * Shows on right-click with options like Play, Queue, Go to Artist, etc.
 */
import { useEffect, useRef } from 'react';
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
  ShoppingCart,
  ExternalLink,
  FileText,
} from 'lucide-react';
import type { Track } from '../../types';
import { isExternalTrack } from '../../types';
import { generateAllSearchUrls } from '../../utils/storeLinks';

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
  onDownloadAnalysis?: () => void;
  onRemoveFromDownloads?: () => void;
  // Favorite toggle
  isFavorite?: boolean;
  onToggleFavorite?: () => void;
  // Bulk selection props (for mobile long-press)
  selectedCount?: number;
  onPlaySelected?: () => void;
  onAddSelectedToPlaylist?: () => void;
  onClearSelection?: () => void;
}

interface MenuItemProps {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  iconClassName?: string;
}

function MenuItem({ icon, label, onClick, disabled, iconClassName }: MenuItemProps) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="w-full flex items-center gap-3 px-3 py-2 text-sm text-left hover:bg-zinc-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
    >
      <span className={iconClassName || "text-zinc-400"}>{icon}</span>
      <span>{label}</span>
    </button>
  );
}

function MenuDivider() {
  return <div className="my-1 border-t border-zinc-700" />;
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
  isFavorite,
  onToggleFavorite,
  selectedCount = 0,
  onDownloadAnalysis,
  onPlaySelected,
  onAddSelectedToPlaylist,
  onClearSelection,
}: TrackContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);

  // Close on click outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose();
      }
    };

    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleEscape);

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [onClose]);

  // Adjust position to keep menu in viewport
  useEffect(() => {
    if (menuRef.current) {
      const rect = menuRef.current.getBoundingClientRect();
      const viewportWidth = window.innerWidth;
      const viewportHeight = window.innerHeight;
      const isMobile = viewportWidth < 768;

      if (isMobile) {
        // On mobile, center horizontally with padding
        const padding = 16;
        const menuWidth = Math.min(rect.width, viewportWidth - padding * 2);
        menuRef.current.style.left = `${(viewportWidth - menuWidth) / 2}px`;
        menuRef.current.style.width = `${menuWidth}px`;

        // Adjust vertical position if menu would go off-screen
        if (rect.bottom > viewportHeight) {
          menuRef.current.style.top = `${Math.max(padding, viewportHeight - rect.height - padding)}px`;
        }
      } else {
        // Desktop: adjust horizontal position if menu would go off-screen
        if (rect.right > viewportWidth) {
          menuRef.current.style.left = `${position.x - rect.width}px`;
        }

        // Adjust vertical position if menu would go off-screen
        if (rect.bottom > viewportHeight) {
          menuRef.current.style.top = `${position.y - rect.height}px`;
        }
      }
    }
  }, [position]);

  const handleAction = (action: () => void) => {
    action();
    onClose();
  };

  const showBulkActions = selectedCount > 1;

  return (
    <div
      ref={menuRef}
      className="fixed z-50 min-w-[200px] py-1 bg-zinc-800 border border-zinc-700 rounded-lg shadow-xl"
      style={{
        left: position.x,
        top: position.y,
      }}
    >
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
      <div className="px-3 py-2 border-b border-zinc-700">
        <div className="text-sm font-medium text-white truncate">
          {track.title || 'Unknown'}
        </div>
        <div className="text-xs text-zinc-400 truncate">
          {track.artist || 'Unknown Artist'}
        </div>
      </div>

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
      {onDownloadAnalysis && (
        <MenuItem
          icon={<FileText className="w-4 h-4" />}
          label="Download Track Analysis"
          onClick={() => handleAction(onDownloadAnalysis)}
        />
      )}

      {/* Remove from Downloads */}
      {onRemoveFromDownloads && (
        <MenuItem
          icon={<Trash2 className="w-4 h-4" />}
          label="Remove from Downloads"
          onClick={() => handleAction(onRemoveFromDownloads)}
        />
      )}

      {/* Playlist */}
      <MenuItem
        icon={<ListPlus className="w-4 h-4" />}
        label="Add to Playlist..."
        onClick={() => handleAction(onAddToPlaylist)}
      />

      {/* Purchase links for unmatched external tracks */}
      {isExternalTrack(track) && !track.matched_track_id && (
        <>
          <MenuDivider />
          {generateAllSearchUrls(track.artist || '', track.title || '', track.album || undefined).map(({ key, name, url }, idx) => (
            <MenuItem
              key={key}
              icon={idx === 0 ? <ShoppingCart className="w-4 h-4" /> : <ExternalLink className="w-4 h-4" />}
              label={`Buy on ${name}`}
              onClick={() => {
                window.open(url, '_blank');
                onClose();
              }}
            />
          ))}
        </>
      )}

      <MenuDivider />

      {/* AI Actions */}
      <MenuItem
        icon={<Sparkles className="w-4 h-4" />}
        label="Make Playlist From This..."
        onClick={() => handleAction(onMakePlaylist)}
      />
    </div>
  );
}

