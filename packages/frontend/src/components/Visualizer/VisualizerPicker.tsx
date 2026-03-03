/**
 * Visualizer Picker Component.
 *
 * Dropdown/popup for selecting between visualizers.
 */
import { useState, useRef, useEffect } from 'react';
import { ChevronDown, Sparkles, BarChart3, Image, Palette, Type, Music, Video } from 'lucide-react';
import { getVisualizers } from './types';
import { useVisualizerStore } from '../../stores/visualizerStore';

// Icon mapping for visualizers
const visualizerIcons: Record<string, typeof Sparkles> = {
  'cosmic-orb': Sparkles,
  'frequency-bars': BarChart3,
  'album-kaleidoscope': Image,
  'color-flow': Palette,
  'typography-wave': Type,
  'lyric-pulse': Music,
  'music-video': Video,
};

export function VisualizerPicker() {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const { visualizerId, setVisualizerId } = useVisualizerStore();

  const visualizers = getVisualizers();
  const currentVisualizer = visualizers.find(v => v.metadata.id === visualizerId);

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
          </div>
        </div>
      )}
    </div>
  );
}
