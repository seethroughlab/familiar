/**
 * AmbientControls — 4-control panel with segmented toggles.
 */

import { useThemeStore } from '../../stores/themeStore';
import type {
  AmbientControls as AmbientControlsType,
  AmbientIntensity,
  SnippetLength,
  TransitionDensity,
  FilterPreset,
} from '../../player/ambient/types';

interface Props {
  controls: AmbientControlsType;
  onChange: (updates: Partial<AmbientControlsType>) => void;
}

export function AmbientControls({ controls, onChange }: Props) {
  const light = useThemeStore((s) => s.resolvedTheme === 'light');

  return (
    <div className="flex flex-col gap-3 px-4">
      <SegmentedControl<AmbientIntensity>
        label="Intensity"
        value={controls.intensity}
        options={[
          { value: 'quiet', label: 'Quiet' },
          { value: 'balanced', label: 'Balanced' },
          { value: 'immersive', label: 'Immersive' },
        ]}
        onChange={(v) => onChange({ intensity: v })}
        light={light}
      />

      <SegmentedControl<SnippetLength>
        label="Snippet Length"
        value={controls.snippetLength}
        options={[
          { value: 8, label: '8s' },
          { value: 16, label: '16s' },
          { value: 24, label: '24s' },
        ]}
        onChange={(v) => onChange({ snippetLength: v })}
        light={light}
      />

      <SegmentedControl<TransitionDensity>
        label="Transitions"
        value={controls.transitionDensity}
        options={[
          { value: 'sparse', label: 'Sparse' },
          { value: 'moderate', label: 'Moderate' },
          { value: 'lush', label: 'Lush' },
        ]}
        onChange={(v) => onChange({ transitionDensity: v })}
        light={light}
      />

      <SegmentedControl<FilterPreset>
        label="Filter"
        value={controls.filterPreset}
        options={[
          { value: 'all', label: 'All' },
          { value: 'soft', label: 'Soft' },
          { value: 'dark', label: 'Dark' },
          { value: 'instrumental', label: 'Inst.' },
        ]}
        onChange={(v) => onChange({ filterPreset: v })}
        light={light}
      />
    </div>
  );
}

interface SegmentedControlProps<T extends string | number> {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
  light: boolean;
}

function SegmentedControl<T extends string | number>({
  label, value, options, onChange, light,
}: SegmentedControlProps<T>) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className={`text-xs font-medium flex-shrink-0 w-20 ${light ? 'text-zinc-500' : 'text-zinc-400'}`}>
        {label}
      </span>
      <div className={`flex-1 flex rounded-lg p-0.5 ${light ? 'bg-zinc-100' : 'bg-zinc-800'}`}>
        {options.map((opt) => (
          <button
            key={String(opt.value)}
            onClick={() => onChange(opt.value)}
            className={`flex-1 text-xs py-1.5 rounded-md transition-colors font-medium ${
              value === opt.value
                ? light
                  ? 'bg-white text-zinc-900 shadow-sm'
                  : 'bg-zinc-700 text-white'
                : light
                  ? 'text-zinc-500'
                  : 'text-zinc-500'
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  );
}
