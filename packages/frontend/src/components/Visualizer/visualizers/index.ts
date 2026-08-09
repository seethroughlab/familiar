/**
 * Visualizer index - lazily registers all visualizers.
 *
 * Metadata is registered synchronously so the picker shows all options immediately.
 * Components are wrapped with React.lazy() and only loaded when rendered.
 */
import { lazy } from 'react';
import { registerVisualizer } from '../types';

registerVisualizer(
  { id: 'reactive-terrain', name: 'Reactive Terrain', description: 'Neon wireframe landscape driven by the spectrum, flashing on every beat', usesMetadata: true },
  lazy(() => import('./ReactiveTerrain'))
);
registerVisualizer(
  { id: 'beat-tiles', name: 'Beat Tiles', description: 'Album cover split into tiles that pop to the beat', usesMetadata: true },
  lazy(() => import('./BeatTiles'))
);
registerVisualizer(
  { id: 'lyrics', name: 'Lyrics', description: 'Scrolling synced lyrics over a drifting field of the song\'s words', usesMetadata: true },
  lazy(() => import('./ScrollingLyrics'))
);
registerVisualizer(
  { id: 'music-video', name: 'Music Video', description: 'Search and play synced music videos from YouTube', usesMetadata: false },
  lazy(() => import('./MusicVideo'))
);
// The word field on its own, without the lyric column and vignette `ScrollingLyrics` layers over
// it. Same `LyricWordField` scene, so the two cannot drift apart.
registerVisualizer(
  { id: 'lyric-storm', name: 'Lyric Storm', description: 'The song\'s own words drifting through a dark 3D space, reacting to the music', usesMetadata: true },
  lazy(() => import('./LyricStorm'))
);
