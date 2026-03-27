import { useRef, useEffect } from 'react';
import { useShuffleWeightStore, SHUFFLE_PRESETS } from '../../stores/shuffleWeightStore';

interface ShuffleWeightPopoverProps {
  isOpen: boolean;
  onClose: () => void;
  buttonRef: React.RefObject<HTMLButtonElement | null>;
  position?: 'above' | 'below';
}

export function ShuffleWeightPopover({ isOpen, onClose, buttonRef, position = 'above' }: ShuffleWeightPopoverProps) {
  const popupRef = useRef<HTMLDivElement>(null);

  const enabled = useShuffleWeightStore((s) => s.enabled);
  const activePreset = useShuffleWeightStore((s) => s.activePreset);
  const setEnabled = useShuffleWeightStore((s) => s.setEnabled);
  const setActivePreset = useShuffleWeightStore((s) => s.setActivePreset);

  // Close on click outside
  useEffect(() => {
    if (!isOpen) return;

    const handleClickOutside = (e: MouseEvent) => {
      if (
        popupRef.current &&
        buttonRef.current &&
        !popupRef.current.contains(e.target as Node) &&
        !buttonRef.current.contains(e.target as Node)
      ) {
        onClose();
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isOpen, onClose, buttonRef]);

  if (!isOpen) return null;

  const positionClass = position === 'above'
    ? 'bottom-full mb-2'
    : 'top-full mt-2';

  return (
    <div
      ref={popupRef}
      className={`absolute ${positionClass} left-1/2 -translate-x-1/2 w-60 bg-zinc-900 border border-zinc-700 rounded-lg shadow-xl z-50`}
    >
      <div className="p-3 border-b border-zinc-700">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium text-white">Weighted Shuffle</span>
          <label className="relative inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
              className="sr-only peer"
            />
            <div className="w-9 h-5 bg-zinc-600 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-amber-500 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-amber-500"></div>
          </label>
        </div>
      </div>

      {enabled && (
        <div className="p-2">
          <div className="space-y-0.5">
            {SHUFFLE_PRESETS.map((preset) => (
              <button
                key={preset.id}
                onClick={() => {
                  setActivePreset(preset.id);
                  onClose();
                }}
                className={`w-full text-left px-3 py-2 rounded-md transition-colors ${
                  activePreset === preset.id
                    ? 'bg-amber-500/20 text-amber-400'
                    : 'text-zinc-300 hover:bg-zinc-800'
                }`}
              >
                <div className="text-sm font-medium">{preset.name}</div>
                <div className="text-xs text-zinc-500">{preset.description}</div>
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="p-2 border-t border-zinc-700">
        <button
          onClick={() => {
            onClose();
            window.dispatchEvent(new Event('navigate-to-settings'));
          }}
          className="block w-full text-center text-xs text-zinc-400 hover:text-white py-1 transition-colors"
        >
          More options in Settings
        </button>
      </div>
    </div>
  );
}
