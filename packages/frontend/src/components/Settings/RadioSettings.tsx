import { Sparkles } from 'lucide-react';
import { useRadioStore } from '../../stores/radioStore';
import { INSERT_EVERY_N_TRACKS } from '../../player/radio/radioController';

/**
 * Opt-in for radio suggestions (ADR-0005).
 *
 * Off by default: this inserts tracks the listener did not choose into a queue they are
 * already enjoying, so turning it on should be their decision.
 */
export function RadioSettings() {
  const enabled = useRadioStore((s) => s.enabled);
  const setEnabled = useRadioStore((s) => s.setEnabled);

  return (
    <div className="bg-zinc-800/50 dark:bg-zinc-800/50 light:bg-zinc-100 rounded-lg p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Sparkles className="w-5 h-5 text-amber-400" />
          <div>
            <h4 className="text-sm font-medium text-white dark:text-white light:text-zinc-900">Radio Suggestions</h4>
            <p className="text-xs text-zinc-400 dark:text-zinc-400 light:text-zinc-600">
              Slip in a track you might like every {INSERT_EVERY_N_TRACKS} songs, matched on
              sound and your listening history
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
        <p className="mt-3 text-xs text-zinc-500 dark:text-zinc-500 light:text-zinc-600">
          Suggestions are marked with <Sparkles className="w-3 h-3 inline text-amber-400" /> in the
          queue. Rejecting one teaches it what not to pick again.
        </p>
      )}
    </div>
  );
}
