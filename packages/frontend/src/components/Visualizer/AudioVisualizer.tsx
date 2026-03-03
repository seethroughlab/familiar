/**
 * Audio Visualizer Component.
 *
 * Dynamically renders the selected visualizer from the registry.
 * Passes the full VisualizerProps API to each visualizer component.
 */
import { Suspense } from 'react';
import { RefreshCw } from 'lucide-react';
import type { Track, TrackFeatures } from '../../types';
import type { LyricLine } from '../../api';
import { getVisualizer, DEFAULT_VISUALIZER_ID } from './types';
import { useVisualizerStore } from '../../stores/visualizerStore';
import { ErrorBoundary } from '../ErrorBoundary';

// Import all visualizers to register them
import './visualizers';

interface AudioVisualizerProps {
  track?: Track | null;
  artworkUrl?: string | null;
  lyrics?: LyricLine[] | null;
  isPlaying?: boolean;
  features?: TrackFeatures | null;
  className?: string;
}

function LoadingFallback() {
  return (
    <div className="w-full h-full bg-[#0a0015] flex items-center justify-center">
      <div className="w-16 h-16 border-4 border-purple-500 border-t-transparent rounded-full animate-spin" />
    </div>
  );
}

function VisualizerErrorFallback() {
  return (
    <div className="w-full h-full bg-[#0a0015] flex flex-col items-center justify-center gap-4">
      <p className="text-zinc-400 text-sm">Visualizer failed to load</p>
      <button
        onClick={() => window.location.reload()}
        className="flex items-center gap-2 px-4 py-2 bg-zinc-800 hover:bg-zinc-700
                   rounded-lg text-sm text-zinc-300 transition-colors"
      >
        <RefreshCw className="w-4 h-4" />
        Reload
      </button>
    </div>
  );
}

export function AudioVisualizer({
  track = null,
  artworkUrl = null,
  lyrics = null,
  isPlaying = false,
  features = null,
  className = '',
}: AudioVisualizerProps) {
  const { visualizerId } = useVisualizerStore();

  // Get the current visualizer component
  const visualizer = getVisualizer(visualizerId) || getVisualizer(DEFAULT_VISUALIZER_ID);

  if (!visualizer) {
    return (
      <div className={`w-full h-full bg-[#0a0015] flex items-center justify-center ${className}`}>
        <span className="text-zinc-500">No visualizer available</span>
      </div>
    );
  }

  const VisualizerComponent = visualizer.component;

  return (
    <div className={`w-full h-full ${className}`}>
      <ErrorBoundary
        name="visualizer"
        fallback={<VisualizerErrorFallback />}
      >
        <Suspense fallback={<LoadingFallback />}>
          <VisualizerComponent
            track={track}
            artworkUrl={artworkUrl}
            lyrics={lyrics}
            currentTime={0}
            duration={0}
            isPlaying={isPlaying}
            features={features}
          />
        </Suspense>
      </ErrorBoundary>
    </div>
  );
}

// Re-export picker and types for convenience
export { VisualizerPicker } from './VisualizerPicker';
// eslint-disable-next-line react-refresh/only-export-components -- Re-exporting utility functions alongside component
export { getVisualizers, getVisualizer, type VisualizerMetadata } from './types';
