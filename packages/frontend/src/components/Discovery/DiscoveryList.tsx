import type { DiscoveryItem } from './types';
import { DiscoveryCard } from './DiscoveryCard';

interface DiscoveryListProps {
  items: DiscoveryItem[];
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
 * List layout for discovery items
 * Used for tracks and metadata-focused display
 */
export function DiscoveryList({
  items,
  onItemClick,
  onItemPlay,
  className = '',
  currentTrackId = null,
  isPlaying = false,
  onTogglePlay,
}: DiscoveryListProps) {

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
        />
      ))}
    </div>
  );
}
