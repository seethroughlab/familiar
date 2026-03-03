import type { DiscoveryItem } from './types';
import { DiscoveryCard } from './DiscoveryCard';
import { usePlayerStore } from '../../stores/playerStore';

interface DiscoveryGridProps {
  items: DiscoveryItem[];
  columns?: 2 | 3 | 4 | 5 | 6;
  onItemClick?: (item: DiscoveryItem) => void;
  onItemPlay?: (item: DiscoveryItem) => void;
  onAddToWishlist?: (item: DiscoveryItem) => void;
  className?: string;
}

/**
 * Grid layout for discovery items
 * Used for albums and visual browsing
 */
export function DiscoveryGrid({
  items,
  columns = 4,
  onItemClick,
  onItemPlay,
  onAddToWishlist,
  className = '',
}: DiscoveryGridProps) {
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

  const gridColsClass = {
    2: 'grid-cols-2',
    3: 'grid-cols-2 sm:grid-cols-3',
    4: 'grid-cols-2 sm:grid-cols-3 md:grid-cols-4',
    5: 'grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5',
    6: 'grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6',
  }[columns];

  return (
    <div className={`grid ${gridColsClass} gap-3 ${className}`}>
      {items.map((item, idx) => (
        <DiscoveryCard
          key={`${item.id || item.name}-${item.subtitle || ''}-${idx}`}
          item={item}
          layout="grid"
          isPlaying={isItemPlaying(item)}
          onClick={() => onItemClick?.(item)}
          onPlay={() => handlePlay(item)}
          onAddToWishlist={onAddToWishlist ? () => onAddToWishlist(item) : undefined}
        />
      ))}
    </div>
  );
}
