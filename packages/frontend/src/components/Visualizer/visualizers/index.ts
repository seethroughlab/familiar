/**
 * Visualizer index - lazily registers all visualizers.
 *
 * Metadata is registered synchronously so the picker shows all options immediately.
 * Components are wrapped with React.lazy() and only loaded when rendered.
 */
import { lazy } from 'react';
import { registerVisualizer } from '../types';

registerVisualizer(
  { id: 'cosmic-orb', name: 'Cosmic Orb', description: 'Glowing orb with album colors and reflective ground', usesMetadata: true },
  lazy(() => import('./CosmicOrb'))
);
registerVisualizer(
  { id: 'frequency-bars', name: 'Frequency Bars', description: 'Enhanced spectrum analyzer with 128 bars', usesMetadata: false },
  lazy(() => import('./FrequencyBars'))
);
registerVisualizer(
  { id: 'album-kaleidoscope', name: 'Album Kaleidoscope', description: 'Shader-based kaleidoscope with RGB split', usesMetadata: true },
  lazy(() => import('./AlbumKaleidoscope'))
);
registerVisualizer(
  { id: 'lyrics', name: 'Lyrics', description: 'Karaoke-style lyrics with next-line preview', usesMetadata: true },
  lazy(() => import('./LyricStorm'))
);
registerVisualizer(
  { id: 'rain-window', name: 'Rain Window', description: 'Peaceful rain on glass with soft bokeh lights', usesMetadata: true },
  lazy(() => import('./RainWindow'))
);
registerVisualizer(
  { id: 'music-video', name: 'Music Video', description: 'Search and play synced music videos from YouTube', usesMetadata: false },
  lazy(() => import('./MusicVideo'))
);
