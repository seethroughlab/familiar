import type { DiscoveryItem } from './types';
import { DiscoveryCard } from './DiscoveryCard';
import { usePlayerStore } from '../../stores/playerStore';

interface DiscoveryListProps {
  items: DiscoveryItem[];
  onItemClick?: (item: DiscoveryItem) => void;
  onItemPlay?: (item: DiscoveryItem) => void;
  onAddToWishlist?: (item: DiscoveryItem) => void;
  className?: string;
}

/**
 * List layout for discovery items
 * Used for tracks and metadata-focused display
 */
export function DiscoveryList({
  items,
  onItemClick,
  onItemPlay,
  onAddToWishlist,
  className = '',
}: DiscoveryListProps) {
  const currentTrack = usePlayerStore((s) => s.currentTrack);
  const isPlaying = usePlayerStore((s) => s.isPlaying);
  const setIsPlaying = usePlayerStore((s) => s.setIsPlaying);

  const isItemPlaying = (item: DiscoveryItem): boolean => {
    return !!(item.id && currentTrack?.id === item.id && isPlaying);
  };

  const handlePlay = (item: DiscoveryItem) => {
    if (item.id && currentTrack?.id === item.id) {
      setIsPlaying(!isPlaying);
    } else {
      onItemPlay?.(item);
    }
  };

  return (
    <div className={`space-y-1 ${className}`}>
      {items.map((item, idx) => (
        <DiscoveryCard
          key={`${item.id || item.name}-${item.subtitle || ''}-${idx}`}
          item={item}
          layout="list"
          isPlaying={isItemPlaying(item)}
          onClick={() => onItemClick?.(item)}
          onPlay={() => handlePlay(item)}
          onAddToWishlist={onAddToWishlist ? () => onAddToWishlist(item) : undefined}
        />
      ))}
    </div>
  );
}
