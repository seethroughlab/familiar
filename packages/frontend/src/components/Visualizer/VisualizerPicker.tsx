/**
 * Visualizer Picker Component.
 *
 * Dropdown/popup for selecting between visualizers.
 */
import { useState, useRef, useEffect } from 'react';
import { ChevronDown, Sparkles, Image, Type, Video, AlertTriangle, CloudLightning } from 'lucide-react';
import { getVisualizers } from './types';
import { useVisualizerStore } from '../../stores/visualizerStore';
import { useVisualizerPluginStore } from '../../stores/visualizerPluginStore';

// Icon mapping for visualizers
const visualizerIcons: Record<string, typeof Sparkles> = {
  'reactive-terrain': Sparkles,
  'beat-tiles': Image,
  'lyrics': Type,
  'music-video': Video,
  'lyric-storm': CloudLightning,
};

export function VisualizerPicker() {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const { visualizerId, setVisualizerId, glowLevel, setGlowLevel } = useVisualizerStore();

  const visualizers = getVisualizers();
  const currentVisualizer = visualizers.find(v => v.metadata.id === visualizerId);

  // ADR-0034 points 7 and 8: a plugin that was refused, or that crashed, says so here. Anything
  // that loaded is already in `visualizers` above and needs no separate row.
  const troubled = useVisualizerPluginStore((s) => s.records).filter((r) => r.status !== 'loaded');

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
    setIsOpen(false);
  };

  const CurrentIcon = currentVisualizer
    ? visualizerIcons[currentVisualizer.metadata.id] || Sparkles
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
          {currentVisualizer?.metadata.name || 'Visualizer'}
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
            {visualizers.map(({ metadata }) => {
              const Icon = visualizerIcons[metadata.id] || Sparkles;
              const isSelected = metadata.id === visualizerId;

              return (
                <button
                  key={metadata.id}
                  onClick={() => handleSelect(metadata.id)}
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
                      {metadata.name}
                      {metadata.usesMetadata && (
                        <span className="text-[10px] px-1.5 py-0.5 bg-purple-500/30 text-purple-300 rounded">
                          METADATA
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-zinc-500 mt-0.5">
                      {metadata.description}
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
                  <div
                    key={`${record.id ?? 'unnamed'}-${index}`}
                    className="flex items-start gap-3 p-3 text-left"
                  >
                    <div className="p-2 rounded-lg bg-zinc-800">
                      <AlertTriangle className="w-4 h-4 text-amber-500" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="font-medium text-zinc-400">
                        {record.name ?? record.id ?? 'Unnamed plugin'}
                      </div>
                      <div className="text-xs text-zinc-500 mt-0.5">
                        {record.detail}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
