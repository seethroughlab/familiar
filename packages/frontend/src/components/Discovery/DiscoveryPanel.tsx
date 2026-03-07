import { useState } from 'react';
import { ChevronDown, ChevronUp, Sparkles } from 'lucide-react';
import type { DiscoverySection, DiscoveryItem, DiscoveryPanelProps } from './types';
import { DiscoverySectionView } from './DiscoverySectionView';
import { DiscoveryLoading } from './DiscoveryLoading';
import { DiscoveryEmpty } from './DiscoveryEmpty';

/**
 * Main discovery panel container with unified branding
 *
 * Features:
 * - Purple accent branding with sparkle icon
 * - Multi-section support with tabs
 * - Collapsible option
 * - Loading and empty states
 */
export function DiscoveryPanel({
  sections,
  title = 'Discover',
  sources,
  loading = false,
  emptyMessage,
  collapsible = false,
  defaultExpanded = true,
  onItemClick,
  onItemPlay,
}: DiscoveryPanelProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);
  const [activeTabId, setActiveTabId] = useState<string | null>(null);

  // Filter sections to only those with items
  const activeSections = sections.filter((s) => s.items.length > 0);

  // Initialize active tab to first section with items
  const effectiveActiveTab = activeTabId || activeSections[0]?.id || null;

  // Handle loading state
  if (loading) {
    return (
      <div className="py-4">
        <DiscoveryLoading />
      </div>
    );
  }

  // Handle empty state
  if (activeSections.length === 0) {
    if (emptyMessage) {
      return (
        <div className="py-4">
          <DiscoveryEmpty message={emptyMessage} />
        </div>
      );
    }
    return null;
  }

  // Calculate total item count
  const itemCount = activeSections.reduce((sum, s) => sum + s.items.length, 0);

  // Render header content
  const renderHeaderContent = () => (
    <>
      <div className="flex items-center gap-2">
        <Sparkles className="w-5 h-5 text-purple-400" />
        <span className="font-medium">{title}</span>
        {sources && sources.length > 0 && (
          <span className="text-xs text-zinc-500">via {sources.join(', ')}</span>
        )}
      </div>
      <div className="flex items-center gap-2">
        <span className="text-xs text-zinc-500">{itemCount}</span>
        {collapsible && (
          isExpanded ? (
            <ChevronUp className="w-5 h-5 text-zinc-400" />
          ) : (
            <ChevronDown className="w-5 h-5 text-zinc-400" />
          )
        )}
      </div>
    </>
  );

  // Render tabs for multi-section mode
  const renderTabs = () => {
    if (activeSections.length <= 1) return null;

    return (
      <div className="flex gap-1 mb-4">
        {activeSections.map((section) => (
          <button
            key={section.id}
            onClick={() => setActiveTabId(section.id)}
            className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
              effectiveActiveTab === section.id
                ? 'bg-purple-600 text-white'
                : 'text-zinc-400 hover:text-white hover:bg-zinc-800'
            }`}
          >
            {section.title} ({section.items.length})
          </button>
        ))}
      </div>
    );
  };

  // Render content
  const renderContent = () => {
    const activeSection = activeSections.find((s) => s.id === effectiveActiveTab) || activeSections[0];
    if (!activeSection) return null;

    return (
      <div>
        {renderTabs()}
        <DiscoverySectionView
          section={activeSection}
          showHeader={false}
          onItemClick={onItemClick}
          onItemPlay={onItemPlay}
        />
      </div>
    );
  };

  // Collapsible mode
  if (collapsible) {
    return (
      <div>
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="w-full flex items-center justify-between px-2 py-2 hover:bg-zinc-800/50 rounded-lg transition-colors"
        >
          {renderHeaderContent()}
        </button>
        {isExpanded && <div className="mt-2">{renderContent()}</div>}
      </div>
    );
  }

  // Non-collapsible mode
  return (
    <div>
      <div className="flex items-center justify-between px-2 py-2">
        {renderHeaderContent()}
      </div>
      <div className="mt-2">{renderContent()}</div>
    </div>
  );
}

/**
 * Simplified panel for single-section use cases
 */
interface SimpleDiscoveryPanelProps {
  title?: string;
  items: DiscoveryItem[];
  entityType: 'track' | 'album' | 'artist';
  layout?: 'list' | 'grid';
  sources?: string[];
  loading?: boolean;
  emptyMessage?: string;
  collapsible?: boolean;
  defaultExpanded?: boolean;
  onItemClick?: (item: DiscoveryItem) => void;
  onItemPlay?: (item: DiscoveryItem) => void;
}

export function SimpleDiscoveryPanel({
  title = 'Discover',
  items,
  entityType,
  layout = 'list',
  ...props
}: SimpleDiscoveryPanelProps) {
  const section: DiscoverySection = {
    id: 'main',
    title,
    entityType,
    items,
    layout,
  };

  return <DiscoveryPanel {...props} title={title} sections={[section]} />;
}
