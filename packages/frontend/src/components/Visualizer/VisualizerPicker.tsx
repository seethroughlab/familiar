/**
 * Visualizer Picker Component.
 *
 * Dropdown/popup for selecting between visualizers.
 */
import { useState, useRef, useEffect } from 'react';
import { ChevronDown, Sparkles, Image, Type, Video, AlertTriangle, CloudLightning } from 'lucide-react';
import { useVisualizerCatalog } from './useVisualizerCatalog';
import { useVisualizerStore } from '../../stores/visualizerStore';
import { useVisualizerPluginStore } from '../../stores/visualizerPluginStore';
import { useVisualizerAutoSelectStore } from '../../stores/visualizerAutoSelectStore';
import { useActiveVisualizerId } from '../../hooks/useAutoSelectedVisualizer';

// Icon mapping for visualizers
const visualizerIcons: Record<string, typeof Sparkles> = {
  'reactive-terrain': Sparkles,
  'beat-tiles': Image,
  'lyrics': Type,
  'music-video': Video,
  'lyric-storm': CloudLightning,
};

/**
 * A row that cannot be selected, because there is nothing to select — it exists so a problem has
 * somewhere to be said. Shared by the two such sections rather than written twice: a refused plugin
 * (ADR-0034 point 7) and a loaded plugin whose affinity was partly unreadable (ADR-0064 point 3)
 * look the same and mean different things, and filtering one list two ways would have conflated
 * them, since ignored declarations belong to plugins that *did* load.
 */
function ProblemRow({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="flex items-start gap-3 p-3 text-left">
      <div className="p-2 rounded-lg bg-zinc-800">
        <AlertTriangle className="w-4 h-4 text-amber-500" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="font-medium text-zinc-400">{title}</div>
        <div className="text-xs text-zinc-500 mt-0.5">{detail}</div>
      </div>
    </div>
  );
}

export function VisualizerPicker() {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const { setVisualizerId, glowLevel, setGlowLevel, autoSelect, setAutoSelect } =
    useVisualizerStore();
  const { chosenId, unranked, ignoredByVisualizer } = useVisualizerAutoSelectStore();

  const visualizers = useVisualizerCatalog();

  // What is actually drawing — shared with `FullPlayer`, which gates its layout on the same answer.
  const activeId = useActiveVisualizerId();
  const currentVisualizer = visualizers.find(v => v.id === activeId);

  const records = useVisualizerPluginStore((s) => s.records);

  // ADR-0034 points 7 and 8: a plugin that was refused, or that crashed, says so here. Anything
  // that loaded is already in `visualizers` above and needs no separate row.
  const troubled = records.filter((r) => r.status !== 'loaded');

  // ADR-0064 point 3: declarations that were not understood, from both halves — the client checks
  // structure while parsing the manifest, the server checks the tag vocabulary it owns. Neither is
  // a refusal; these plugins are loaded and in the list above.
  const ignoredEntries = visualizers
    .map((entry) => {
      const fromManifest = records.find((r) => r.id === entry.id)?.ignored ?? [];
      const fromServer = ignoredByVisualizer[entry.id] ?? [];
      return { id: entry.id, name: entry.name, ignored: [...fromManifest, ...fromServer] };
    })
    .filter((entry) => entry.ignored.length > 0);

  // Close on click outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [isOpen]);

  // Close on escape
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIsOpen(false);
    };

    if (isOpen) {
      document.addEventListener('keydown', handleEscape);
      return () => document.removeEventListener('keydown', handleEscape);
    }
  }, [isOpen]);

  const handleSelect = (id: string) => {
    setVisualizerId(id);
    // **Choosing one turns auto-select off.** Leaving it on would let the next track overrule the
    // choice that was just made, which is the silent override ADR-0064 point 7 rules out — and
    // picking from this list is about as explicit as a preference gets.
    setAutoSelect(false);
    setIsOpen(false);
  };

  const CurrentIcon = currentVisualizer
    ? visualizerIcons[currentVisualizer.id] || Sparkles
    : Sparkles;

  return (
    <div ref={containerRef} className="relative">
      {/* Trigger button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={`flex items-center gap-2 px-3 py-2 rounded-lg transition-colors ${
          isOpen
            ? 'bg-white/20 text-white'
            : 'bg-white/10 text-zinc-300 hover:bg-white/15 hover:text-white'
        }`}
      >
        <CurrentIcon className="w-4 h-4" />
        <span className="text-sm font-medium">
          {currentVisualizer?.name || 'Visualizer'}
        </span>
        <ChevronDown
          className={`w-4 h-4 transition-transform ${isOpen ? 'rotate-180' : ''}`}
        />
      </button>

      {/* Dropdown */}
      {isOpen && (
        <div className="absolute top-full right-0 mt-2 w-[calc(100vw-2rem)] sm:w-64 max-w-64 bg-zinc-900 border border-zinc-700 rounded-lg shadow-xl z-50 overflow-hidden">
          <div className="p-2 border-b border-zinc-700">
            <span className="text-xs text-zinc-500 uppercase tracking-wide">
              Choose Visualizer
            </span>
          </div>

          <div className="px-3 py-2.5 border-b border-zinc-700">
            <label className="flex items-center justify-between gap-3 cursor-pointer">
              <span className="min-w-0">
                <span className="text-xs text-zinc-400 block">Match to the music</span>
                <span className="text-[11px] text-zinc-500 block mt-0.5">
                  {unranked
                    ? 'This track has not been analysed yet'
                    : 'Pick a visualizer to suit each track'}
                </span>
              </span>
              <input
                type="checkbox"
                checked={autoSelect}
                onChange={(e) => setAutoSelect(e.target.checked)}
                className="w-4 h-4 shrink-0 rounded accent-purple-500 cursor-pointer"
              />
            </label>
          </div>

          <div className="px-3 py-2.5 border-b border-zinc-700">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-xs text-zinc-400">Glow</span>
              <span className="text-xs text-zinc-500 tabular-nums">{glowLevel}%</span>
            </div>
            <input
              type="range"
              min={0}
              max={100}
              value={glowLevel}
              onChange={(e) => setGlowLevel(Number(e.target.value))}
              className="w-full h-1.5 bg-zinc-700 rounded-full appearance-none cursor-pointer accent-purple-500 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-purple-500"
            />
          </div>

          <div className="max-h-80 overflow-y-auto">
            {visualizers.map((entry) => {
              const Icon = visualizerIcons[entry.id] || Sparkles;
              const isSelected = entry.id === activeId;
              const isAutoChoice = autoSelect && chosenId === entry.id;

              return (
                <button
                  key={entry.id}
                  onClick={() => handleSelect(entry.id)}
                  className={`w-full flex items-start gap-3 p-3 text-left transition-colors ${
                    isSelected
                      ? 'bg-purple-500/20 text-white'
                      : 'text-zinc-300 hover:bg-white/5 hover:text-white'
                  }`}
                >
                  <div
                    className={`p-2 rounded-lg ${
                      isSelected ? 'bg-purple-500/30' : 'bg-zinc-800'
                    }`}
                  >
                    <Icon className="w-4 h-4" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="font-medium flex items-center gap-2">
                      {entry.name}
                      {isAutoChoice && (
                        <span className="text-[10px] px-1.5 py-0.5 bg-emerald-500/30 text-emerald-300 rounded">
                          AUTO
                        </span>
                      )}
                      {/*
                        The METADATA badge went with the registry. `usesMetadata` said whether a
                        visualizer looked at the track; under ADR-0087 point 2 every document
                        receives everything and decides for itself, so there is nothing to declare.
                      */}
                    </div>
                    <div className="text-xs text-zinc-500 mt-0.5">
                      {entry.description}
                    </div>
                  </div>
                  {isSelected && (
                    <div className="w-2 h-2 rounded-full bg-purple-500 mt-2" />
                  )}
                </button>
              );
            })}

            {/* Not buttons: there is nothing to select. A refused plugin is here so that dropping a
                file into the Visualizers folder and seeing nothing happen has an explanation, which
                is the whole of ADR-0034 point 7. */}
            {troubled.length > 0 && (
              <div className="border-t border-zinc-700">
                <div className="px-3 pt-3 pb-1">
                  <span className="text-xs text-zinc-500 uppercase tracking-wide">
                    Not loaded
                  </span>
                </div>
                {troubled.map((record, index) => (
                  <ProblemRow
                    key={`${record.id ?? 'unnamed'}-${index}`}
                    title={record.name ?? record.id ?? 'Unnamed plugin'}
                    detail={record.detail ?? ''}
                  />
                ))}
              </div>
            )}

            {/* ADR-0064 point 3. These plugins work and are in the list above — this is only the
                part of what they declared that nothing understood. An author whose typo vanished
                silently has no way to find it, and refusing the visualizer over it would be a far
                worse trade. */}
            {ignoredEntries.length > 0 && (
              <div className="border-t border-zinc-700">
                <div className="px-3 pt-3 pb-1">
                  <span className="text-xs text-zinc-500 uppercase tracking-wide">
                    Ignored in manifest
                  </span>
                </div>
                {ignoredEntries.map((entry) => (
                  <ProblemRow key={entry.id} title={entry.name} detail={entry.ignored.join(', ')} />
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
