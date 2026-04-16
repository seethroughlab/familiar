import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowUpDown, Check, ChevronDown, ChevronUp } from 'lucide-react';
import { getColumnDef } from '../Library/columnDefinitions';
import { getVisibleColumns, type ColumnConfig } from '../../stores/columnStore';

interface Props {
  columns: ColumnConfig[];
  sortBy: string | null;
  sortOrder: 'asc' | 'desc';
  toggleSort: (columnId: string) => void;
  clearSort: () => void;
}

interface SortOption {
  id: string;
  label: string;
}

export function MobilePlaylistSortControl({
  columns,
  sortBy,
  sortOrder,
  toggleSort,
  clearSort,
}: Props) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const options = useMemo<SortOption[]>(() => {
    const opts: SortOption[] = [{ id: 'title', label: 'Title' }];
    for (const colId of getVisibleColumns(columns)) {
      const def = getColumnDef(colId);
      if (def?.sortField) {
        opts.push({ id: colId, label: def.label });
      }
    }
    return opts;
  }, [columns]);

  useEffect(() => {
    if (!open) return;
    const handle = (e: MouseEvent | TouchEvent) => {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handle);
    document.addEventListener('touchstart', handle);
    return () => {
      document.removeEventListener('mousedown', handle);
      document.removeEventListener('touchstart', handle);
    };
  }, [open]);

  const activeLabel = sortBy === null
    ? null
    : options.find((o) => o.id === sortBy)?.label ?? null;

  const DirectionIcon = sortOrder === 'asc' ? ChevronUp : ChevronDown;

  return (
    <div
      ref={containerRef}
      className="sm:hidden sticky top-0 z-10 bg-zinc-900 border-b border-zinc-800 px-3 py-2 flex justify-end"
      data-testid="mobile-sort-control"
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-xs text-zinc-300 bg-zinc-800 hover:bg-zinc-700 active:bg-zinc-700 rounded-full px-3 py-1.5"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <ArrowUpDown className="w-3.5 h-3.5" />
        {activeLabel ? (
          <>
            <span>{activeLabel}</span>
            <DirectionIcon className="w-3.5 h-3.5" />
          </>
        ) : (
          <span>Sort</span>
        )}
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-3 top-full mt-1 min-w-[12rem] bg-zinc-900 border border-zinc-700 rounded-lg shadow-lg overflow-hidden"
        >
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              clearSort();
              setOpen(false);
            }}
            className="w-full flex items-center justify-between gap-2 px-3 py-2.5 text-sm text-zinc-200 hover:bg-zinc-800 active:bg-zinc-800 text-left"
          >
            <span>Default order</span>
            {sortBy === null && <Check className="w-4 h-4 text-blue-400" />}
          </button>
          <div className="border-t border-zinc-800" />
          {options.map((opt) => {
            const isActive = sortBy === opt.id;
            const ActiveIcon = sortOrder === 'asc' ? ChevronUp : ChevronDown;
            return (
              <button
                key={opt.id}
                type="button"
                role="menuitem"
                onClick={() => toggleSort(opt.id)}
                className={`w-full flex items-center justify-between gap-2 px-3 py-2.5 text-sm hover:bg-zinc-800 active:bg-zinc-800 text-left ${
                  isActive ? 'text-white' : 'text-zinc-200'
                }`}
              >
                <span>{opt.label}</span>
                {isActive && <ActiveIcon className="w-4 h-4 text-blue-400" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
