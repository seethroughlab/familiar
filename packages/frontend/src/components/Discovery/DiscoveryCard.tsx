import { Play, Pause, Disc, Disc3, User, Plus } from 'lucide-react';
import type { DiscoveryItem, LayoutType } from './types';
import { MatchScoreBadge } from './MatchScoreBadge';
import { ExternalLinkPills } from './ExternalLinkPills';
import { AlbumArtwork } from '../AlbumArtwork';

interface DiscoveryCardProps {
  item: DiscoveryItem;
  layout?: LayoutType;
  isPlaying?: boolean;
  onClick?: () => void;
  onPlay?: () => void;
  onAddToWishlist?: () => void;
}

/**
 * Check if URL is Last.fm's default placeholder image
 */
function isLastFmPlaceholder(url: string | undefined): boolean {
  return url?.includes('2a96cbd8b46e442fc41c2b86b821562f') ?? false;
}

/**
 * Unified discovery card component
 * - List layout: horizontal with text info
 * - Grid layout: square with overlay text
 */
export function DiscoveryCard({
  item,
  layout = 'list',
  isPlaying = false,
  onClick,
  onPlay,
  onAddToWishlist,
}: DiscoveryCardProps) {
  const isClickable = item.inLibrary && onClick;
  const hasValidImageUrl = item.imageUrl && !isLastFmPlaceholder(item.imageUrl);

  // Determine if we can use AlbumArtwork (for albums and tracks with artist+album info)
  const canUseAlbumArtwork =
    item.entityType !== 'artist' &&
    item.playbackContext?.artist &&
    item.playbackContext?.album;

  const handlePlay = (e: React.MouseEvent) => {
    e.stopPropagation();
    onPlay?.();
  };

  const handleAddToWishlist = (e: React.MouseEvent) => {
    e.stopPropagation();
    onAddToWishlist?.();
  };

  // Render the artwork/icon section
  const renderArtwork = (size: 'small' | 'large') => {
    const sizeClasses = size === 'small' ? 'w-10 h-10' : 'w-full aspect-square';
    const iconSize = size === 'small' ? 'w-5 h-5' : 'w-8 h-8';
    const isArtist = item.entityType === 'artist';
    const roundedClass = isArtist ? 'rounded-full' : 'rounded';

    return (
      <div className={`relative ${sizeClasses} flex-shrink-0`}>
        {canUseAlbumArtwork ? (
          <AlbumArtwork
            artist={item.playbackContext!.artist}
            album={item.playbackContext!.album}
            trackId={item.playbackContext?.trackId || item.id}
            size="thumb"
            className={`${sizeClasses} ${roundedClass}`}
          />
        ) : hasValidImageUrl ? (
          <div className={`relative ${sizeClasses} bg-zinc-700 ${roundedClass}`}>
            <img
              src={item.imageUrl}
              alt={item.name}
              className={`${sizeClasses} object-cover ${roundedClass}`}
              onError={(e) => {
                e.currentTarget.style.display = 'none';
              }}
            />
            {/* Fallback icon behind image */}
            <div className={`absolute inset-0 flex items-center justify-center -z-10 ${roundedClass}`}>
              {isArtist ? (
                <User className={`${iconSize} text-zinc-400`} />
              ) : (
                <Disc className={`${iconSize} text-zinc-400`} />
              )}
            </div>
          </div>
        ) : (
          <div className={`${sizeClasses} bg-zinc-700 flex items-center justify-center ${roundedClass}`}>
            {isArtist ? (
              <User className={`${iconSize} text-zinc-400`} />
            ) : item.entityType === 'track' ? (
              <Disc3 className={`${iconSize} text-zinc-400`} />
            ) : (
              <Disc className={`${iconSize} text-zinc-400`} />
            )}
          </div>
        )}

        {/* Play button overlay for in-library items */}
        {item.inLibrary && onPlay && (
          <button
            onClick={handlePlay}
            className={`absolute inset-0 flex items-center justify-center ${roundedClass} bg-black/60 transition-opacity ${
              isPlaying ? 'opacity-100' : 'opacity-100 sm:opacity-0 sm:group-hover:opacity-100'
            }`}
          >
            {isPlaying ? (
              <Pause className={size === 'small' ? 'w-4 h-4' : 'w-6 h-6'} fill="currentColor" />
            ) : (
              <Play className={size === 'small' ? 'w-4 h-4' : 'w-6 h-6'} fill="currentColor" />
            )}
          </button>
        )}
      </div>
    );
  };

  // Grid layout rendering
  if (layout === 'grid') {
    return (
      <div
        onClick={() => isClickable && onClick?.()}
        className={`group relative overflow-hidden rounded-lg bg-zinc-800/50 transition-all ${
          isClickable ? 'cursor-pointer hover:bg-zinc-800' : ''
        } ${!item.inLibrary ? 'opacity-75' : ''}`}
      >
        {renderArtwork('large')}

        {/* Text overlay at bottom */}
        <div className="absolute bottom-0 left-0 right-0 p-3 bg-gradient-to-t from-black/80 to-transparent">
          <div className={`font-medium text-sm truncate ${isPlaying ? 'text-green-500' : ''}`}>
            {item.name}
          </div>
          {item.subtitle && (
            <div className="text-xs text-zinc-400 truncate">{item.subtitle}</div>
          )}
        </div>

        {/* Match score badge in top-right */}
        {item.matchScore !== undefined && (
          <div className="absolute top-2 right-2">
            <MatchScoreBadge score={item.matchScore} inLibrary={item.inLibrary} />
          </div>
        )}

        {/* External links for non-library items */}
        {!item.inLibrary && item.externalLinks && (
          <div className="absolute bottom-12 right-2">
            <ExternalLinkPills links={item.externalLinks} />
          </div>
        )}

        {/* Add to Wishlist button for non-library items */}
        {!item.inLibrary && onAddToWishlist && (
          <button
            onClick={handleAddToWishlist}
            className="absolute top-2 left-2 p-1.5 rounded-full bg-purple-600 hover:bg-purple-500 transition-colors opacity-0 group-hover:opacity-100"
            title="Add to Wishlist"
          >
            <Plus className="w-4 h-4" />
          </button>
        )}
      </div>
    );
  }

  // List layout rendering (default)
  return (
    <div
      onClick={() => isClickable && onClick?.()}
      className={`group flex items-center gap-3 p-2 rounded-lg transition-colors ${
        isClickable ? 'cursor-pointer hover:bg-zinc-800/50' : ''
      } ${isPlaying ? 'bg-zinc-800/30' : ''} ${!item.inLibrary ? 'opacity-75' : ''}`}
    >
      {renderArtwork('small')}

      {/* Info */}
      <div className="flex-1 min-w-0">
        <div className={`font-medium text-sm truncate ${isPlaying ? 'text-green-500' : ''}`}>
          {item.name}
        </div>
        {item.subtitle && (
          <div className="text-xs text-zinc-400 truncate">{item.subtitle}</div>
        )}
        {item.matchReason && (
          <div className="text-xs text-zinc-500 truncate">{item.matchReason}</div>
        )}
      </div>

      {/* Right side: match score, badges, links, wishlist button */}
      <div className="flex items-center gap-2 flex-shrink-0">
        {item.inLibrary ? (
          item.matchScore !== undefined && (
            <MatchScoreBadge score={item.matchScore} inLibrary />
          )
        ) : (
          <>
            {item.matchScore !== undefined && (
              <MatchScoreBadge score={item.matchScore} />
            )}
            {item.externalLinks && <ExternalLinkPills links={item.externalLinks} />}
            {onAddToWishlist && (
              <button
                onClick={handleAddToWishlist}
                className="p-1.5 rounded-full bg-purple-600 hover:bg-purple-500 transition-colors"
                title="Add to Wishlist"
              >
                <Plus className="w-4 h-4" />
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}
