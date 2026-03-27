import { Shuffle } from 'lucide-react';
import { useShuffleWeightStore, SHUFFLE_PRESETS } from '../../stores/shuffleWeightStore';

export function ShuffleWeightSettings() {
  const enabled = useShuffleWeightStore((s) => s.enabled);
  const activePreset = useShuffleWeightStore((s) => s.activePreset);
  const setEnabled = useShuffleWeightStore((s) => s.setEnabled);
  const setActivePreset = useShuffleWeightStore((s) => s.setActivePreset);

  return (
    <div className="bg-zinc-800/50 dark:bg-zinc-800/50 light:bg-zinc-100 rounded-lg p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Shuffle className="w-5 h-5 text-amber-400" />
          <div>
            <h4 className="text-sm font-medium text-white dark:text-white light:text-zinc-900">Weighted Shuffle</h4>
            <p className="text-xs text-zinc-400 dark:text-zinc-400 light:text-zinc-600">
              Bias shuffle toward discovery, favorites, or variety
            </p>
          </div>
        </div>
        <label className="relative inline-flex items-center cursor-pointer">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
            className="sr-only peer"
          />
          <div className="w-11 h-6 bg-zinc-600 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-amber-500 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-amber-500"></div>
        </label>
      </div>

      {enabled && (
        <div className="mt-4 space-y-2">
          {SHUFFLE_PRESETS.map((preset) => (
            <button
              key={preset.id}
              onClick={() => setActivePreset(preset.id)}
              className={`w-full text-left px-4 py-3 rounded-lg transition-colors ${
                activePreset === preset.id
                  ? 'bg-amber-500/20 border border-amber-500/30'
                  : 'bg-zinc-700/30 dark:bg-zinc-700/30 light:bg-zinc-200/50 border border-transparent hover:bg-zinc-700/50'
              }`}
            >
              <div className={`text-sm font-medium ${
                activePreset === preset.id ? 'text-amber-400' : 'text-white dark:text-white light:text-zinc-900'
              }`}>
                {preset.name}
              </div>
              <div className="text-xs text-zinc-400 dark:text-zinc-400 light:text-zinc-600 mt-0.5">
                {preset.description}
              </div>
            </button>
          ))}

          <p className="text-xs text-zinc-500 mt-3 px-1">
            Long-press the shuffle button in the player for quick access.
          </p>
        </div>
      )}
    </div>
  );
}
