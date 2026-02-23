import { useState, useRef, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { ShoppingCart, ExternalLink } from 'lucide-react';
import { generateAllSearchUrls, STORE_STYLES } from '../../utils/storeLinks';

interface Props {
  artist: string;
  title: string;
  album?: string | null;
}

export function StoreSearchLinks({ artist, title, album }: Props) {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const links = generateAllSearchUrls(artist, title, album ?? undefined);
  if (links.length === 0) return null;

  const toggle = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    setOpen((v) => !v);
  }, []);

  // Click-outside and escape dismissal
  useEffect(() => {
    if (!open) return;

    const handleClick = (e: MouseEvent) => {
      const target = e.target as Node;
      if (buttonRef.current?.contains(target) || menuRef.current?.contains(target)) return;
      setOpen(false);
    };

    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };

    document.addEventListener('mousedown', handleClick);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('mousedown', handleClick);
      document.removeEventListener('keydown', handleKey);
    };
  }, [open]);

  // Compute dropdown position
  const getPosition = () => {
    if (!buttonRef.current) return { top: 0, left: 0 };
    const rect = buttonRef.current.getBoundingClientRect();
    const menuWidth = 220;
    const menuHeight = links.length * 40 + 16; // rough estimate

    let top = rect.bottom + 4;
    let left = rect.right - menuWidth;

    // Flip up if near bottom
    if (top + menuHeight > window.innerHeight - 16) {
      top = rect.top - menuHeight - 4;
    }
    // Push right if overflowing left
    if (left < 8) {
      left = 8;
    }
    // Push left if overflowing right
    if (left + menuWidth > window.innerWidth - 8) {
      left = window.innerWidth - menuWidth - 8;
    }

    return { top, left };
  };

  return (
    <>
      <button
        ref={buttonRef}
        onClick={toggle}
        title="Search music stores"
        className="p-1 text-zinc-500 hover:text-white transition-colors rounded hover:bg-zinc-700/50"
      >
        <ShoppingCart className="w-4 h-4" />
      </button>

      {open &&
        createPortal(
          <div
            ref={menuRef}
            className="fixed z-50 w-[220px] py-2 bg-zinc-800 border border-zinc-700 rounded-lg shadow-xl"
            style={getPosition()}
          >
            {links.map(({ key, name, url }) => {
              const style = STORE_STYLES[key] || {
                color: 'bg-zinc-600 hover:bg-zinc-500',
                abbrev: key.slice(0, 2).toUpperCase(),
              };
              return (
                <a
                  key={key}
                  href={url}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={(e) => {
                    e.stopPropagation();
                    setOpen(false);
                  }}
                  className="flex items-center gap-2 px-3 py-1.5 hover:bg-zinc-700/60 transition-colors cursor-pointer"
                >
                  <span
                    className={`px-1.5 py-0.5 text-[10px] font-medium rounded ${style.color}`}
                  >
                    {style.abbrev}
                  </span>
                  <span className="flex-1 text-sm text-zinc-200 truncate">
                    {name}
                  </span>
                  <ExternalLink className="w-3.5 h-3.5 text-zinc-500 flex-shrink-0" />
                </a>
              );
            })}
          </div>,
          document.body,
        )}
    </>
  );
}
