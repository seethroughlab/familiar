/**
 * Audio Visualizer Component.
 *
 * Dynamically renders the selected visualizer from the registry.
 * Passes the full VisualizerProps API to each visualizer component.
 */
import { useCallback } from 'react';
import { RefreshCw } from 'lucide-react';
import type { Track, TrackFeatures } from '../../types';
import type { LyricLine } from '../../api';
import { DocumentVisualizer } from './DocumentVisualizer';
import { VisualizerDebugPanel } from './VisualizerDebugPanel';
import { debugPanelEnabled } from './visualizerMetrics';
import { useVisualizerCatalog } from './useVisualizerCatalog';
import { DEFAULT_VISUALIZER_ID } from './constants';
import { useVisualizerStore } from '../../stores/visualizerStore';
import { useVisualizerPluginStore } from '../../stores/visualizerPluginStore';
import { useAutoSelectedVisualizer, useActiveVisualizerId } from '../../hooks/useAutoSelectedVisualizer';
import { ErrorBoundary } from '../ErrorBoundary';

interface AudioVisualizerProps {
  track?: Track | null;
  artworkUrl?: string | null;
  lyrics?: LyricLine[] | null;
  isPlaying?: boolean;
  features?: TrackFeatures | null;
  /** Current playback position in seconds — drives time-synced visualizers (e.g. lyrics) */
  currentTime?: number;
  /** Track duration in seconds */
  duration?: number;
  className?: string;
}

/**
 * What a crashed visualizer falls back to (ADR-0034 point 8).
 *
 * **The album art, when there is any** — the same square the player shows when no visualizer is
 * available, so a third-party plugin dying degrades to the ordinary no-visualizer screen instead of
 * an error message that implies the app is broken. The message and the reload button stay for the
 * case where there is no artwork either, because then a black rectangle would be indistinguishable
 * from a visualizer that simply renders nothing.
 */
function VisualizerErrorFallback({ artworkUrl }: { artworkUrl: string | null }) {
  if (artworkUrl) {
    return (
      <div className="w-full h-full bg-[#0a0015] flex items-center justify-center p-8">
        <img
          src={artworkUrl}
          alt=""
          className="max-w-full max-h-full object-contain rounded-lg shadow-2xl"
        />
      </div>
    );
  }

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
  currentTime = 0,
  duration = 0,
  className = '',
}: AudioVisualizerProps) {
  const { visualizerId } = useVisualizerStore();
  const catalog = useVisualizerCatalog();
  const markPluginFailed = useVisualizerPluginStore((s) => s.markFailed);

  // ADR-0064 point 7. **This is the only caller**, so the ranking is asked for once per track no
  // matter how many things want to know the answer — wired here rather than at each call site
  // because both surfaces render through this component. The value is read back through
  // `useActiveVisualizerId` so the "which visualizer is on" rule has exactly one definition.
  useAutoSelectedVisualizer(track?.id);
  // The id we are *asking* for, which is not necessarily the one that resolves — see `activeId`
  // below, which is what actually rendered after the fallbacks.
  const requestedId = useActiveVisualizerId();

  // Falls back to the listener's own choice before the default, so an auto-chosen plugin that has
  // since been removed lands on what they picked rather than on Reactive Terrain.
  const byId = (id: string | undefined) => (id ? catalog.find((entry) => entry.id === id) : undefined);
  const visualizer =
    byId(requestedId) ||
    byId(visualizerId) ||
    byId(DEFAULT_VISUALIZER_ID) ||
    catalog[0];
  const activeId = visualizer?.id;

  // ADR-0034 point 8: the picker marks the plugin as failed. A built-in id is not in the plugin
  // records and `markFailed` ignores it, so this is safe to call for whatever crashed.
  const handleError = useCallback(
    (error: Error) => {
      if (activeId) markPluginFailed(activeId, error.message || 'The visualizer crashed while rendering.');
    },
    [activeId, markPluginFailed]
  );

  if (!visualizer) {
    return (
      <div className={`w-full h-full bg-[#0a0015] flex items-center justify-center ${className}`}>
        <span className="text-zinc-500">No visualizer available</span>
      </div>
    );
  }

  return (
    <div className={`w-full h-full ${className}`}>
      {debugPanelEnabled() && <VisualizerDebugPanel />}
      <ErrorBoundary
        // **Keyed by the visualizer**, so switching away from a crashed one gets a fresh boundary.
        // Without it the boundary stays latched and every subsequent choice renders the fallback,
        // which reads as "all the visualizers are broken" when only one is.
        key={activeId}
        name="visualizer"
        onError={handleError}
        fallback={<VisualizerErrorFallback artworkUrl={artworkUrl} />}
      >
        {/*
          A document, not a component (ADR-0087 point 1). The boundary above now catches only what
          *this* page does — a plugin that throws takes down its own frame and nothing else, which
          is point 5's isolation being structural rather than defensive.
        */}
        <DocumentVisualizer
          src={visualizer.url}
          track={track}
          features={features}
          artworkUrl={artworkUrl}
          lyrics={lyrics}
          currentTime={currentTime}
          duration={duration}
          isPlaying={isPlaying}
        />
      </ErrorBoundary>
    </div>
  );
}

// Re-export picker and types for convenience
export { VisualizerPicker } from './VisualizerPicker';
// eslint-disable-next-line react-refresh/only-export-components -- Re-exporting utility functions alongside component
export { type VisualizerMetadata } from './types';
