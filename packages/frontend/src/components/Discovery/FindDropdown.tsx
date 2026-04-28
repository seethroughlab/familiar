/**
 * FindDropdown — shared "Find" affordance for non-library discovery cards.
 *
 * Used by ExternalAlbumCard ("Albums you might want", "New releases") and
 * DiscoveryCard's artist grid ("Artists to Explore"). Renders a portaled,
 * right-aligned menu so the dropdown escapes any overflow-hidden ancestors
 * and isn't painted over by sibling cards (see commit f0b317c for the bug
 * this pattern fixes).
 */
import { useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ShoppingBag, ExternalLink } from 'lucide-react';

export interface FindLink {
  name: string;
  url: string;
}

interface FindDropdownProps {
  links: FindLink[];
  /** Optional callback fired when a link is opened (e.g. analytics). */
  onOpenExternal?: (url: string) => void;
  /** Visible label on the trigger button. Defaults to "Find". */
  label?: string;
  /** Aria label for accessibility. */
  ariaLabel?: string;
}

export function FindDropdown({
  links,
  onOpenExternal,
  label = 'Find',
  ariaLabel = 'Find this item',
}: FindDropdownProps) {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);

  useLayoutEffect(() => {
    if (!open || !buttonRef.current) {
      setPos(null);
      return;
    }
    const compute = () => {
      const rect = buttonRef.current!.getBoundingClientRect();
      const MENU_WIDTH = 176; // matches w-44 (11rem)
      setPos({ top: rect.bottom + 4, left: rect.right - MENU_WIDTH });
    };
    compute();
    window.addEventListener('scroll', compute, true);
    window.addEventListener('resize', compute);
    return () => {
      window.removeEventListener('scroll', compute, true);
      window.removeEventListener('resize', compute);
    };
  }, [open]);

  if (links.length === 0) return null;

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        className="flex items-center gap-1 px-2 py-1 rounded-md bg-zinc-900/80 backdrop-blur-sm text-xs text-zinc-200 hover:bg-zinc-800 transition-colors"
        aria-label={ariaLabel}
      >
        <ShoppingBag className="w-3.5 h-3.5" />
        {label}
      </button>
      {open && pos &&
        createPortal(
          <>
            <div
              className="fixed inset-0 z-[60]"
              onClick={(e) => {
                e.stopPropagation();
                setOpen(false);
              }}
            />
            <div
              className="fixed w-44 z-[70] rounded-md border border-zinc-700 bg-zinc-900 shadow-lg overflow-hidden"
              style={{ top: pos.top, left: pos.left }}
              onClick={(e) => e.stopPropagation()}
            >
              {links.map((link) => (
                <a
                  key={link.url}
                  href={link.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={(e) => {
                    e.stopPropagation();
                    onOpenExternal?.(link.url);
                    setOpen(false);
                  }}
                  className="flex items-center justify-between gap-2 px-3 py-2 text-xs text-zinc-200 hover:bg-zinc-800 transition-colors"
                >
                  <span>{link.name}</span>
                  <ExternalLink className="w-3 h-3 text-zinc-400" />
                </a>
              ))}
            </div>
          </>,
          document.body,
        )}
    </>
  );
}
