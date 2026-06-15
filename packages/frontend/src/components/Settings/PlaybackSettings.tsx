import { Volume2, AudioLines, Monitor, Radio } from 'lucide-react';
import { useAudioSettingsStore } from '../../stores/audioSettingsStore';
import type { NormalizationMode } from '../../stores/audioSettingsStore';
import { useOutputStore } from '../../stores/outputStore';

export function PlaybackSettings() {
  const networkOutputActive = useOutputStore((s) => s.activeOutputId !== null);
  const {
    crossfadeEnabled,
    crossfadeDuration,
    setCrossfadeEnabled,
    setCrossfadeDuration,
    normalizationEnabled,
    normalizationMode,
    normalizationTargetLufs,
    normalizationPreamp,
    normalizationPreventClipping,
    setNormalizationEnabled,
    setNormalizationMode,
    setNormalizationTargetLufs,
    setNormalizationPreamp,
    setNormalizationPreventClipping,
  } = useAudioSettingsStore();

  const getDurationLabel = (duration: number): string => {
    if (duration === 0) return 'Gapless';
    return `${duration}s`;
  };

  const modeLabels: Record<NormalizationMode, string> = {
    track: 'Track',
    album: 'Album',
    auto: 'Auto',
  };

  const modeDescriptions: Record<NormalizationMode, string> = {
    track: 'Normalize each track independently',
    album: 'Normalize by album average (preserves album dynamics)',
    auto: 'Album mode when playing albums, track mode otherwise',
  };

  return (
    <div className="space-y-4">
      {/* Crossfade */}
      <div className="bg-zinc-800/50 dark:bg-zinc-800/50 light:bg-white rounded-lg p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Volume2 className="w-5 h-5 text-purple-400" />
            <div>
              <h4 className="font-medium text-white dark:text-white light:text-zinc-900">
                Crossfade
              </h4>
              <p className="text-sm text-zinc-400 dark:text-zinc-400 light:text-zinc-600">
                Smoothly transition between tracks
              </p>
            </div>
          </div>

          <label className="relative inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={crossfadeEnabled}
              onChange={(e) => setCrossfadeEnabled(e.target.checked)}
              className="sr-only peer"
            />
            <div className="w-11 h-6 bg-zinc-600 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-purple-500 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-purple-500"></div>
          </label>
        </div>

        {networkOutputActive && (
          <div className="mt-4 flex items-center gap-2 text-xs text-zinc-500 bg-zinc-700/50 rounded-lg px-3 py-2">
            <Radio className="w-3.5 h-3.5 flex-shrink-0" />
            <span>
              Crossfade isn't available on network outputs (WiiM / Sonos / UPnP).
              Tracks play to their natural end while casting.
            </span>
          </div>
        )}

        {crossfadeEnabled && (
          <div className="mt-4 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm text-zinc-400 dark:text-zinc-400 light:text-zinc-600">
                Duration
              </span>
              <span className="text-sm font-medium text-white dark:text-white light:text-zinc-900">
                {getDurationLabel(crossfadeDuration)}
              </span>
            </div>

            <div className="relative">
              <input
                type="range"
                min="0"
                max="10"
                step="1"
                value={crossfadeDuration}
                onChange={(e) => setCrossfadeDuration(Number(e.target.value))}
                className="w-full h-2 bg-zinc-700 rounded-lg appearance-none cursor-pointer accent-purple-500"
              />
              <div className="flex justify-between text-xs text-zinc-500 mt-1">
                <span>Gapless</span>
                <span>10s</span>
              </div>
            </div>

            <p className="text-xs text-zinc-500 dark:text-zinc-500 light:text-zinc-500">
              {crossfadeDuration === 0
                ? 'Tracks will transition instantly without any gap'
                : `Tracks will overlap and fade for ${crossfadeDuration} second${crossfadeDuration > 1 ? 's' : ''}`}
            </p>
          </div>
        )}
      </div>

      {/* Volume Normalization */}
      <div className="bg-zinc-800/50 dark:bg-zinc-800/50 light:bg-white rounded-lg p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <AudioLines className="w-5 h-5 text-purple-400" />
            <div>
              <h4 className="font-medium text-white dark:text-white light:text-zinc-900">
                Volume Normalization
              </h4>
              <p className="text-sm text-zinc-400 dark:text-zinc-400 light:text-zinc-600">
                Play all tracks at consistent volume levels
              </p>
            </div>
          </div>

          <label className="relative inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={normalizationEnabled}
              onChange={(e) => setNormalizationEnabled(e.target.checked)}
              className="sr-only peer"
            />
            <div className="w-11 h-6 bg-zinc-600 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-purple-500 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-purple-500"></div>
          </label>
        </div>

        {normalizationEnabled && (
          <div className="mt-4 space-y-4">
            {/* Mode selector */}
            <div>
              <label className="text-sm text-zinc-400 dark:text-zinc-400 light:text-zinc-600 mb-2 block">
                Mode
              </label>
              <div className="flex gap-2">
                {(['track', 'album', 'auto'] as NormalizationMode[]).map((mode) => (
                  <button
                    key={mode}
                    onClick={() => setNormalizationMode(mode)}
                    className={`flex-1 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                      normalizationMode === mode
                        ? 'bg-purple-500 text-white'
                        : 'bg-zinc-700 text-zinc-300 hover:bg-zinc-600'
                    }`}
                  >
                    {modeLabels[mode]}
                  </button>
                ))}
              </div>
              <p className="text-xs text-zinc-500 mt-1">
                {modeDescriptions[normalizationMode]}
              </p>
            </div>

            {/* Target loudness */}
            <div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-zinc-400 dark:text-zinc-400 light:text-zinc-600">
                  Target loudness
                </span>
                <span className="text-sm font-medium text-white dark:text-white light:text-zinc-900">
                  {normalizationTargetLufs} LUFS
                </span>
              </div>
              <input
                type="range"
                min="-23"
                max="-5"
                step="1"
                value={normalizationTargetLufs}
                onChange={(e) => setNormalizationTargetLufs(Number(e.target.value))}
                className="w-full h-2 bg-zinc-700 rounded-lg appearance-none cursor-pointer accent-purple-500 mt-2"
              />
              <div className="flex justify-between text-xs text-zinc-500 mt-1">
                <span>-23 (quiet)</span>
                <span>-14</span>
                <span>-5 (loud)</span>
              </div>
            </div>

            {/* Preamp */}
            <div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-zinc-400 dark:text-zinc-400 light:text-zinc-600">
                  Preamp
                </span>
                <span className="text-sm font-medium text-white dark:text-white light:text-zinc-900">
                  {normalizationPreamp > 0 ? '+' : ''}{normalizationPreamp} dB
                </span>
              </div>
              <input
                type="range"
                min="-6"
                max="6"
                step="0.5"
                value={normalizationPreamp}
                onChange={(e) => setNormalizationPreamp(Number(e.target.value))}
                className="w-full h-2 bg-zinc-700 rounded-lg appearance-none cursor-pointer accent-purple-500 mt-2"
              />
              <div className="flex justify-between text-xs text-zinc-500 mt-1">
                <span>-6 dB</span>
                <span>0</span>
                <span>+6 dB</span>
              </div>
            </div>

            {/* Prevent clipping */}
            <div className="flex items-center justify-between">
              <span className="text-sm text-zinc-400 dark:text-zinc-400 light:text-zinc-600">
                Prevent clipping
              </span>
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={normalizationPreventClipping}
                  onChange={(e) => setNormalizationPreventClipping(e.target.checked)}
                  className="sr-only peer"
                />
                <div className="w-9 h-5 bg-zinc-600 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-purple-500 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-purple-500"></div>
              </label>
            </div>

            {/* Desktop only note */}
            <div className="flex items-center gap-2 text-xs text-zinc-500 bg-zinc-700/50 rounded-lg px-3 py-2">
              <Monitor className="w-3.5 h-3.5 flex-shrink-0" />
              <span>
                Normalization uses Web Audio and is only available on desktop browsers.
                Tracks must be analyzed with loudness data for gain to be applied.
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
