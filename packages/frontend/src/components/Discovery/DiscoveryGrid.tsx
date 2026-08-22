import type { DiscoveryItem } from './types';
import { DiscoveryCard } from './DiscoveryCard';

interface DiscoveryGridProps {
  items: DiscoveryItem[];
  columns?: 2 | 3 | 4 | 5 | 6;
  onItemClick?: (item: DiscoveryItem) => void;
  onItemPlay?: (item: DiscoveryItem) => void;
  /**
   * What the native player is on, when the parent knows (ADR-0083 point 1). Optional: a surface
   * with no transport passes neither, and no item is marked as playing.
   */
  currentTrackId?: string | null;
  isPlaying?: boolean;
  /** Toggle the current item. Absent where there is nothing to toggle. */
  onTogglePlay?: () => void;
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
  className = '',
  currentTrackId = null,
  isPlaying = false,
  onTogglePlay,
}: DiscoveryGridProps) {

  const isItemPlaying = (item: DiscoveryItem): boolean => {
    return !!(item.id && currentTrackId === item.id && isPlaying);
  };

  const handlePlay = (item: DiscoveryItem) => {
    if (item.id && currentTrackId === item.id) {
      onTogglePlay?.();
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
        />
      ))}
    </div>
  );
}
