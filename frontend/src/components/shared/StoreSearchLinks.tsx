import { useState } from 'react';
import { ExternalLink } from 'lucide-react';
import { generateAllSearchUrls, STORE_STYLES } from '../../utils/storeLinks';

interface Props {
  artist: string;
  title: string;
  album?: string | null;
  /** Max links to show before collapsing (default: 3) */
  maxVisible?: number;
}

export function StoreSearchLinks({ artist, title, album, maxVisible = 3 }: Props) {
  const [showAll, setShowAll] = useState(false);

  const links = generateAllSearchUrls(artist, title, album ?? undefined);
  if (links.length === 0) return null;

  const visibleLinks = showAll ? links : links.slice(0, maxVisible);

  return (
    <span className="inline-flex items-center gap-1 flex-wrap">
      {visibleLinks.map(({ key, name, url }) => {
        const style = STORE_STYLES[key] || { color: 'bg-zinc-600 hover:bg-zinc-500', abbrev: key.slice(0, 2).toUpperCase() };
        return (
          <a
            key={key}
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            title={`Search on ${name}`}
            className={`px-2 py-0.5 text-[10px] font-medium rounded transition-colors inline-flex items-center gap-0.5 ${style.color}`}
          >
            {style.abbrev}
            <ExternalLink className="w-2.5 h-2.5" />
          </a>
        );
      })}
      {links.length > maxVisible && !showAll && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            setShowAll(true);
          }}
          className="px-1.5 py-0.5 text-[10px] text-zinc-400 hover:text-white transition-colors"
        >
          +{links.length - maxVisible}
        </button>
      )}
    </span>
  );
}
