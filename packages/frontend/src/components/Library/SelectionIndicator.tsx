/**
 * Selection indicator pill.
 *
 * Floating pill that appears when tracks are selected.
 * Displays count and provides a quick clear button.
 */
import { X } from 'lucide-react';

interface SelectionIndicatorProps {
  selectedCount: number;
  onClear: () => void;
}

export function SelectionIndicator({
  selectedCount,
  onClear,
}: SelectionIndicatorProps) {
  if (selectedCount === 0) {
    return null;
  }

  return (
    <div className="fixed bottom-20 left-1/2 -translate-x-1/2 z-40">
      <div className="flex items-center gap-2 px-4 py-2 bg-purple-600 text-white rounded-full shadow-lg">
        <span className="text-sm font-medium">
          {selectedCount} selected
        </span>
        <button
          onClick={onClear}
          className="p-1 hover:bg-white/20 rounded-full transition-colors"
          aria-label="Clear selection"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
