import { RotateCcw } from 'lucide-react';
import type { TrackMetadataUpdate, TrackMetadataResponse } from '../../../api';

interface Props {
  formData: Partial<TrackMetadataUpdate>;
  metadata: TrackMetadataResponse | undefined;
  onChange: (field: keyof TrackMetadataUpdate, value: unknown) => void;
}

// Musical keys for dropdown
const MUSICAL_KEYS = [
  'C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B',
  'Cm', 'C#m', 'Dm', 'D#m', 'Em', 'Fm', 'F#m', 'Gm', 'G#m', 'Am', 'A#m', 'Bm',
];

export function AnalysisTab({ formData, metadata, onChange }: Props) {
  const userOverrides = formData.user_overrides ?? {};
  const features = metadata?.features;

  // Get effective value (user override if set, otherwise detected)
  const getEffectiveValue = (key: 'bpm' | 'key') => {
    if (userOverrides[key] !== undefined && userOverrides[key] !== null) {
      return userOverrides[key];
    }
    return features?.[key] ?? null;
  };

  // Check if a field has a user override
  const hasOverride = (key: string) => {
    return userOverrides[key] !== undefined && userOverrides[key] !== null;
  };

  // Update a user override
  const setOverride = (key: string, value: number | string | null) => {
    const newOverrides = { ...userOverrides };
    if (value === null || value === '') {
      delete newOverrides[key];
    } else {
      newOverrides[key] = value;
    }
    onChange('user_overrides', Object.keys(newOverrides).length > 0 ? newOverrides : null);
  };

  // Reset a specific override
  const resetOverride = (key: string) => {
    const newOverrides = { ...userOverrides };
    delete newOverrides[key];
    onChange('user_overrides', Object.keys(newOverrides).length > 0 ? newOverrides : null);
  };

  const detectedBpm = features?.bpm;
  const detectedKey = features?.key;

  return (
    <div className="space-y-6">
      <p className="text-sm text-zinc-400">
        Override auto-detected analysis values. Your overrides will be used instead of
        the detected values throughout the app.
      </p>

      {/* BPM Override */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <label className="text-sm font-medium text-zinc-300">BPM (Tempo)</label>
          {hasOverride('bpm') && (
            <button
              onClick={() => resetOverride('bpm')}
              className="flex items-center gap-1 text-xs text-zinc-500 hover:text-zinc-300"
            >
              <RotateCcw className="w-3 h-3" />
              Reset to detected
            </button>
          )}
        </div>
        <div className="flex items-center gap-3">
          <input
            type="number"
            min="20"
            max="300"
            step="0.1"
            value={getEffectiveValue('bpm') ?? ''}
            onChange={(e) => setOverride('bpm', e.target.value ? parseFloat(e.target.value) : null)}
            placeholder="BPM"
            className="w-32 px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent"
          />
          {detectedBpm && (
            <span className="text-sm text-zinc-500">
              Detected: {detectedBpm.toFixed(1)} BPM
              {hasOverride('bpm') && <span className="text-yellow-500 ml-2">(overridden)</span>}
            </span>
          )}
          {!detectedBpm && (
            <span className="text-sm text-zinc-600">Not analyzed</span>
          )}
        </div>
      </div>

      {/* Key Override */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <label className="text-sm font-medium text-zinc-300">Musical Key</label>
          {hasOverride('key') && (
            <button
              onClick={() => resetOverride('key')}
              className="flex items-center gap-1 text-xs text-zinc-500 hover:text-zinc-300"
            >
              <RotateCcw className="w-3 h-3" />
              Reset to detected
            </button>
          )}
        </div>
        <div className="flex items-center gap-3">
          <select
            value={getEffectiveValue('key') ?? ''}
            onChange={(e) => setOverride('key', e.target.value || null)}
            className="w-32 px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent"
          >
            <option value="">Select...</option>
            {MUSICAL_KEYS.map((key) => (
              <option key={key} value={key}>{key}</option>
            ))}
          </select>
          {detectedKey && (
            <span className="text-sm text-zinc-500">
              Detected: {detectedKey}
              {hasOverride('key') && <span className="text-yellow-500 ml-2">(overridden)</span>}
            </span>
          )}
          {!detectedKey && (
            <span className="text-sm text-zinc-600">Not analyzed</span>
          )}
        </div>
      </div>

      {/* Read-only analysis values */}
      {features && (
        <div className="pt-4 border-t border-zinc-800">
          <h4 className="text-sm font-medium text-zinc-400 mb-3">Other Detected Values (read-only)</h4>
          <div className="grid grid-cols-2 gap-3 text-sm">
            {features.energy !== null && (
              <div className="flex justify-between">
                <span className="text-zinc-500">Energy</span>
                <span className="text-zinc-300">{(features.energy * 100).toFixed(0)}%</span>
              </div>
            )}
            {features.danceability !== null && (
              <div className="flex justify-between">
                <span className="text-zinc-500">Danceability</span>
                <span className="text-zinc-300">{(features.danceability * 100).toFixed(0)}%</span>
              </div>
            )}
            {features.valence !== null && (
              <div className="flex justify-between">
                <span className="text-zinc-500">Valence</span>
                <span className="text-zinc-300">{(features.valence * 100).toFixed(0)}%</span>
              </div>
            )}
            {features.acousticness !== null && (
              <div className="flex justify-between">
                <span className="text-zinc-500">Acousticness</span>
                <span className="text-zinc-300">{(features.acousticness * 100).toFixed(0)}%</span>
              </div>
            )}
            {features.instrumentalness !== null && (
              <div className="flex justify-between">
                <span className="text-zinc-500">Instrumentalness</span>
                <span className="text-zinc-300">{(features.instrumentalness * 100).toFixed(0)}%</span>
              </div>
            )}
            {features.speechiness !== null && (
              <div className="flex justify-between">
                <span className="text-zinc-500">Speechiness</span>
                <span className="text-zinc-300">{(features.speechiness * 100).toFixed(0)}%</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
