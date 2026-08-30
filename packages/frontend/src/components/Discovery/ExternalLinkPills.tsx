import { ExternalLink } from 'lucide-react';

interface ExternalLinks {
  bandcamp?: string;
  lastfm?: string;
  amazon?: string;
  apple?: string;
}

interface ExternalLinkPillsProps {
  links: ExternalLinks;
  className?: string;
}

/**
 * External link pills for discovery items not in the library
 * Priority: Bandcamp (teal) > Last.fm (red) > Amazon MP3 (orange) > Apple Music (pink)
 */
export function ExternalLinkPills({ links, className = '' }: ExternalLinkPillsProps) {
  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
  };

  return (
    <div className={`flex items-center gap-1.5 ${className}`}>
      {links.bandcamp && (
        <a
          href={links.bandcamp}
          target="_blank"
          rel="noopener noreferrer"
          onClick={handleClick}
          className="px-2 py-1 text-xs bg-teal-600/20 text-teal-400 hover:bg-teal-600/40 rounded transition-colors"
        >
          Bandcamp
        </a>
      )}
      {links.lastfm && (
        <a
          href={links.lastfm}
          target="_blank"
          rel="noopener noreferrer"
          onClick={handleClick}
          className="px-2 py-1 text-xs bg-danger-strong/20 text-danger hover:bg-danger-strong/40 rounded transition-colors flex items-center gap-1"
        >
          Last.fm
        </a>
      )}
      {links.amazon && (
        <a
          href={links.amazon}
          target="_blank"
          rel="noopener noreferrer"
          onClick={handleClick}
          className="px-2 py-1 text-xs bg-orange-600/20 text-orange-400 hover:bg-orange-600/40 rounded transition-colors"
        >
          Amazon MP3
        </a>
      )}
      {links.apple && (
        <a
          href={links.apple}
          target="_blank"
          rel="noopener noreferrer"
          onClick={handleClick}
          className="px-2 py-1 text-xs bg-pink-600/20 text-pink-400 hover:bg-pink-600/40 rounded transition-colors"
        >
          Apple Music
        </a>
      )}
      {/* Fallback to generic external link if only one link without service pill */}
      {!links.bandcamp && links.lastfm && (
        <a
          href={links.lastfm}
          target="_blank"
          rel="noopener noreferrer"
          onClick={handleClick}
          className="p-1.5 text-zinc-400 hover:text-white hover:bg-zinc-700 rounded transition-colors"
          title="View on Last.fm"
        >
          <ExternalLink className="w-3.5 h-3.5" />
        </a>
      )}
    </div>
  );
}

/**
 * Compact version - just shows icon for non-Bandcamp links
 */
export function ExternalLinkIcon({ links, className = '' }: ExternalLinkPillsProps) {
  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
  };

  // Bandcamp gets a pill, others get an icon
  const url = links.bandcamp || links.lastfm;
  if (!url) return null;

  if (links.bandcamp) {
    return (
      <a
        href={links.bandcamp}
        target="_blank"
        rel="noopener noreferrer"
        onClick={handleClick}
        className={`px-2 py-1 text-xs bg-teal-600/20 text-teal-400 hover:bg-teal-600/40 rounded transition-colors ${className}`}
      >
        Bandcamp
      </a>
    );
  }

  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      onClick={handleClick}
      className={`p-1.5 text-zinc-400 hover:text-white hover:bg-zinc-700 rounded transition-colors ${className}`}
      title="View on Last.fm"
    >
      <ExternalLink className="w-3.5 h-3.5" />
    </a>
  );
}
