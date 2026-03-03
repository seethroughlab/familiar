import { useState } from 'react';
import { RotateCcw } from 'lucide-react';

interface Props {
  value: string | number | null | undefined;
  originalValue: string | number | null | undefined;
  isMixed: boolean;
  onChange: (value: string | number | null) => void;
  type?: 'text' | 'number';
  placeholder?: string;
  min?: number;
  max?: number;
  label: string;
  className?: string;
}

/**
 * Input field for bulk editing that handles "mixed" state.
 *
 * When multiple tracks have different values for a field:
 * - Shows "(Mixed)" as placeholder
 * - Typing replaces the mixed value for all tracks
 * - Can reset to mixed state (no change)
 */
export function MixedValueInput({
  value,
  originalValue,
  isMixed,
  onChange,
  type = 'text',
  placeholder,
  min,
  max,
  label,
  className = '',
}: Props) {
  // Track if user has modified this field
  const [hasEdited, setHasEdited] = useState(false);

  // Display value - show empty if mixed and not edited
  const displayValue = hasEdited ? (value ?? '') : (isMixed ? '' : (value ?? ''));

  // Handle input change
  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setHasEdited(true);
    const rawValue = e.target.value;

    if (rawValue === '') {
      onChange(null);
    } else if (type === 'number') {
      const numValue = parseFloat(rawValue);
      onChange(isNaN(numValue) ? null : numValue);
    } else {
      onChange(rawValue);
    }
  };

  // Reset to original/mixed state
  const handleReset = () => {
    setHasEdited(false);
    onChange(isMixed ? null : originalValue ?? null);
  };

  // Show reset button if:
  // - User has edited the field, OR
  // - Value differs from original (for non-mixed fields)
  const showReset = hasEdited || (!isMixed && value !== originalValue);

  // Dynamic placeholder
  const effectivePlaceholder = isMixed && !hasEdited ? '(Mixed - type to replace)' : placeholder;

  return (
    <div className={`relative ${className}`}>
      <label className="block text-sm font-medium text-zinc-300 mb-1">{label}</label>
      <div className="relative">
        <input
          type={type}
          value={displayValue}
          onChange={handleChange}
          placeholder={effectivePlaceholder}
          min={min}
          max={max}
          className={`w-full px-3 py-2 pr-10 bg-zinc-800 border rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent ${
            isMixed && !hasEdited
              ? 'border-amber-600/50 italic'
              : 'border-zinc-700'
          }`}
        />
        {showReset && (
          <button
            type="button"
            onClick={handleReset}
            className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-zinc-500 hover:text-zinc-300 transition-colors"
            title={isMixed ? 'Reset to mixed (no change)' : 'Reset to original value'}
          >
            <RotateCcw className="w-4 h-4" />
          </button>
        )}
      </div>
      {isMixed && !hasEdited && (
        <p className="text-xs text-amber-500 mt-1">
          Different values across selected tracks
        </p>
      )}
    </div>
  );
}


interface MixedTextAreaProps {
  value: string | null | undefined;
  originalValue: string | null | undefined;
  isMixed: boolean;
  onChange: (value: string | null) => void;
  placeholder?: string;
  label: string;
  rows?: number;
  className?: string;
}

/**
 * TextArea version for longer text fields like lyrics or comments.
 */
export function MixedTextArea({
  value,
  originalValue,
  isMixed,
  onChange,
  placeholder,
  label,
  rows = 4,
  className = '',
}: MixedTextAreaProps) {
  const [hasEdited, setHasEdited] = useState(false);

  const displayValue = hasEdited ? (value ?? '') : (isMixed ? '' : (value ?? ''));

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setHasEdited(true);
    onChange(e.target.value || null);
  };

  const handleReset = () => {
    setHasEdited(false);
    onChange(isMixed ? null : originalValue ?? null);
  };

  const showReset = hasEdited || (!isMixed && value !== originalValue);
  const effectivePlaceholder = isMixed && !hasEdited ? '(Mixed - type to replace)' : placeholder;

  return (
    <div className={className}>
      <div className="flex items-center justify-between mb-1">
        <label className="text-sm font-medium text-zinc-300">{label}</label>
        {showReset && (
          <button
            type="button"
            onClick={handleReset}
            className="flex items-center gap-1 text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
          >
            <RotateCcw className="w-3 h-3" />
            Reset
          </button>
        )}
      </div>
      <textarea
        value={displayValue}
        onChange={handleChange}
        placeholder={effectivePlaceholder}
        rows={rows}
        className={`w-full px-3 py-2 bg-zinc-800 border rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent resize-none ${
          isMixed && !hasEdited
            ? 'border-amber-600/50 italic'
            : 'border-zinc-700'
        }`}
      />
      {isMixed && !hasEdited && (
        <p className="text-xs text-amber-500 mt-1">
          Different values across selected tracks
        </p>
      )}
    </div>
  );
}
