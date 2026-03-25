/**
 * Column header for playlist views with clickable sort indicators.
 * Simplified version of the library's DesktopColumnHeader — no drag-to-reorder
 * or column resizing (those are library-specific).
 */
import { useMemo } from 'react';
import { ChevronUp, ChevronDown } from 'lucide-react';
import { getVisibleColumns, type ColumnConfig } from '../../stores/columnStore';
import { getColumnDef } from '../Library/columnDefinitions';

interface Props {
  columns: ColumnConfig[];
  gridColumns: string;
  sortBy: string | null;
  sortOrder: 'asc' | 'desc';
  toggleSort: (columnId: string) => void;
  clearSort: () => void;
  /** Extra trailing empty header cells (e.g. for heart icon, duration, etc.) */
  trailingCount?: number;
}

export function PlaylistColumnHeader({
  columns,
  gridColumns,
  sortBy,
  sortOrder,
  toggleSort,
  clearSort,
  trailingCount = 2,
}: Props) {
  const visibleColumnIds = useMemo(() => getVisibleColumns(columns), [columns]);

  return (
    <div
      className="hidden sm:grid gap-4 px-4 py-2 text-sm text-zinc-400 border-b border-zinc-800 flex-shrink-0 sticky top-0 z-10 bg-zinc-900"
      style={{ gridTemplateColumns: gridColumns }}
    >
      {/* Index column — click to return to natural order */}
      <div
        onClick={clearSort}
        className={`cursor-pointer hover:text-white flex items-center gap-1 ${
          sortBy === null ? 'text-white' : ''
        }`}
        title="Click to sort by natural order"
      >
        <span>#</span>
        {sortBy === null && (
          <ChevronDown className="w-3 h-3 flex-shrink-0" />
        )}
      </div>

      {/* Title column — always sortable */}
      <div
        onClick={() => toggleSort('title')}
        className={`cursor-pointer hover:text-white flex items-center gap-1 ${
          sortBy === 'title' ? 'text-white' : ''
        }`}
        title="Click to sort by Title"
      >
        <span>Title</span>
        {sortBy === 'title' && (
          sortOrder === 'asc'
            ? <ChevronUp className="w-3 h-3 flex-shrink-0" />
            : <ChevronDown className="w-3 h-3 flex-shrink-0" />
        )}
      </div>

      {/* Dynamic visible columns */}
      {visibleColumnIds.map((colId) => {
        const colDef = getColumnDef(colId);
        if (!colDef) return null;
        const isSortable = !!colDef.sortField;
        const isSorted = sortBy === colId;
        return (
          <div
            key={colId}
            onClick={() => isSortable && toggleSort(colId)}
            className={`truncate flex items-center gap-1 ${
              colDef.align === 'right'
                ? 'justify-end'
                : colDef.align === 'center'
                ? 'justify-center'
                : ''
            } ${isSortable ? 'cursor-pointer hover:text-white' : ''} ${
              isSorted ? 'text-white' : ''
            }`}
            title={isSortable ? `Click to sort by ${colDef.label}` : colDef.label}
          >
            <span>{colDef.shortLabel || colDef.label}</span>
            {isSorted && (
              sortOrder === 'asc'
                ? <ChevronUp className="w-3 h-3 flex-shrink-0" />
                : <ChevronDown className="w-3 h-3 flex-shrink-0" />
            )}
          </div>
        );
      })}

      {/* Trailing empty cells to match the row layout */}
      {Array.from({ length: trailingCount }, (_, i) => (
        <div key={`trailing-${i}`} />
      ))}
    </div>
  );
}
