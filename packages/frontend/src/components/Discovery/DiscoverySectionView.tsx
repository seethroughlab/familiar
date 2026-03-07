import { Disc, Disc3, User } from 'lucide-react';
import type { DiscoverySection, DiscoveryItem } from './types';
import { DiscoveryList } from './DiscoveryList';
import { DiscoveryGrid } from './DiscoveryGrid';

interface DiscoverySectionViewProps {
  section: DiscoverySection;
  onItemClick?: (item: DiscoveryItem) => void;
  onItemPlay?: (item: DiscoveryItem) => void;
  showHeader?: boolean;
  gridColumns?: 2 | 3 | 4 | 5 | 6;
  className?: string;
}

/**
 * Get the default icon for an entity type
 */
function getTypeIcon(entityType: 'album' | 'artist' | 'track') {
  switch (entityType) {
    case 'artist':
      return <User className="w-4 h-4 text-purple-400" />;
    case 'track':
      return <Disc3 className="w-4 h-4 text-purple-400" />;
    default:
      return <Disc className="w-4 h-4 text-purple-400" />;
  }
}

/**
 * Renders a single discovery section with optional header
 */
export function DiscoverySectionView({
  section,
  onItemClick,
  onItemPlay,
  showHeader = true,
  gridColumns = 4,
  className = '',
}: DiscoverySectionViewProps) {
  if (section.items.length === 0) {
    return null;
  }

  const layout = section.layout || 'list';

  return (
    <div className={className}>
      {showHeader && (
        <div className="flex items-center gap-2 mb-3">
          {section.icon || getTypeIcon(section.entityType)}
          <h3 className="font-medium text-sm">{section.title}</h3>
          <span className="text-xs text-zinc-500">({section.items.length})</span>
        </div>
      )}

      {layout === 'grid' ? (
        <DiscoveryGrid
          items={section.items}
          columns={gridColumns}
          onItemClick={onItemClick}
          onItemPlay={onItemPlay}
        />
      ) : (
        <DiscoveryList
          items={section.items}
          onItemClick={onItemClick}
          onItemPlay={onItemPlay}
        />
      )}
    </div>
  );
}
