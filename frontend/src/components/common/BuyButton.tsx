import { useState, useRef, useEffect } from 'react';
import { ShoppingCart, ChevronDown } from 'lucide-react';
import { generateSearchUrl, generateAllSearchUrls, DEFAULT_STORE } from '../../utils/storeLinks';

interface Props {
  artist: string;
  title: string;
  album?: string;
}

export function BuyButton({ artist, title, album }: Props) {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Close on click outside
  useEffect(() => {
    if (!isOpen) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isOpen]);

  const defaultUrl = generateSearchUrl(DEFAULT_STORE, artist, title, album);
  const allStores = generateAllSearchUrls(artist, title, album);

  return (
    <div ref={containerRef} className="relative flex items-center">
      <a
        href={defaultUrl ?? '#'}
        target="_blank"
        rel="noopener noreferrer"
        onClick={(e) => e.stopPropagation()}
        className="p-1 text-zinc-500 hover:text-emerald-400 transition-colors"
        title="Buy on Bandcamp"
      >
        <ShoppingCart className="w-4 h-4" />
      </a>
      <button
        onClick={(e) => {
          e.stopPropagation();
          setIsOpen(!isOpen);
        }}
        className="p-0.5 text-zinc-500 hover:text-zinc-300 transition-colors"
        title="More stores"
      >
        <ChevronDown className="w-3 h-3" />
      </button>

      {isOpen && (
        <div className="absolute bottom-full right-0 mb-1 w-44 bg-zinc-800 border border-zinc-700 rounded-lg shadow-xl z-50 py-1">
          {allStores.map(({ key, name, url }) => (
            <a
              key={key}
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="block px-3 py-1.5 text-sm text-zinc-300 hover:bg-zinc-700 hover:text-white transition-colors"
            >
              {name}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
