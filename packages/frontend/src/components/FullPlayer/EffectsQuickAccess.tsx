import { useState, useRef, useEffect } from 'react';
import { Sliders } from 'lucide-react';
import { useAudioEffectsStore } from '../../stores/audioEffectsStore';
import { areAudioEffectsAvailable } from '../../player/audio/engineInstance';

/**
 * Quick access button for audio effects in the FullPlayer header.
 * Shows a popup with master toggle and preset selection.
 */
export function EffectsQuickAccess() {
  const [isOpen, setIsOpen] = useState(false);
  const popupRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const effectsAvailable = areAudioEffectsAvailable();

  const masterEnabled = useAudioEffectsStore((s) => s.masterEnabled);
  const setMasterEnabled = useAudioEffectsStore((s) => s.setMasterEnabled);
  const presets = useAudioEffectsStore((s) => s.presets);
  const activePresetName = useAudioEffectsStore((s) => s.activePresetName);
  const loadPreset = useAudioEffectsStore((s) => s.loadPreset);

  // Close on click outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (
        popupRef.current &&
        buttonRef.current &&
        !popupRef.current.contains(e.target as Node) &&
        !buttonRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [isOpen]);

  const builtInPresetNames = [
    'Warm Vinyl',
    'Live Concert',
    'Studio Polish',
    'Bass Boost',
    'Dreamy',
  ];

  // Don't show effects button on mobile where effects aren't available
  if (!effectsAvailable) {
    return null;
  }

  return (
    <div className="relative">
      <button
        ref={buttonRef}
        onClick={() => setIsOpen(!isOpen)}
        className={`p-2 rounded-md transition-colors ${masterEnabled
            ? 'bg-purple-500/20 text-purple-400'
            : 'text-zinc-400 hover:text-white hover:bg-white/10'
          }`}
        title="Audio Effects"
      >
        <Sliders className="w-5 h-5" />
      </button>

      {isOpen && (
        <div
          ref={popupRef}
          className="absolute top-full right-0 mt-2 w-56 bg-zinc-900 border border-zinc-700 rounded-lg shadow-xl z-50"
        >
          <div className="p-3 border-b border-zinc-700">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-white">Audio Effects</span>
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={masterEnabled}
                  onChange={(e) => setMasterEnabled(e.target.checked)}
                  className="sr-only peer"
                />
                <div className="w-9 h-5 bg-zinc-600 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-purple-500 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-purple-500"></div>
              </label>
            </div>
          </div>

          {masterEnabled && (
            <div className="p-2">
              <p className="text-xs text-zinc-500 px-2 py-1">Quick Presets</p>
              <div className="space-y-0.5">
                {presets
                  .filter((p) => builtInPresetNames.includes(p.name))
                  .map((preset) => (
                    <button
                      key={preset.name}
                      onClick={() => {
                        loadPreset(preset.name);
                        setIsOpen(false);
                      }}
                      className={`w-full text-left px-3 py-2 text-sm rounded-md transition-colors ${activePresetName === preset.name
                          ? 'bg-purple-500/20 text-purple-400'
                          : 'text-zinc-300 hover:bg-zinc-800'
                        }`}
                    >
                      {preset.name}
                    </button>
                  ))}
              </div>

              {/* Custom presets if any */}
              {presets.some((p) => !builtInPresetNames.includes(p.name)) && (
                <>
                  <p className="text-xs text-zinc-500 px-2 py-1 mt-2">Custom</p>
                  <div className="space-y-0.5">
                    {presets
                      .filter((p) => !builtInPresetNames.includes(p.name))
                      .map((preset) => (
                        <button
                          key={preset.name}
                          onClick={() => {
                            loadPreset(preset.name);
                            setIsOpen(false);
                          }}
                          className={`w-full text-left px-3 py-2 text-sm rounded-md transition-colors ${activePresetName === preset.name
                              ? 'bg-purple-500/20 text-purple-400'
                              : 'text-zinc-300 hover:bg-zinc-800'
                            }`}
                        >
                          {preset.name}
                        </button>
                      ))}
                  </div>
                </>
              )}
            </div>
          )}

          <div className="p-2 border-t border-zinc-700">
            <button
              onClick={() => {
                setIsOpen(false);
                window.dispatchEvent(new Event('navigate-to-settings'));
              }}
              className="block w-full text-center text-xs text-zinc-400 hover:text-white py-1 transition-colors"
            >
              More options in Settings
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
