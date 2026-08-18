/**
 * Visualizer index - lazily registers all visualizers.
 *
 * Metadata is registered synchronously so the picker shows all options immediately.
 * Components are wrapped with React.lazy() and only loaded when rendered.
 */
import { lazy } from 'react';
import { registerVisualizer } from '../types';

/**
 * The built-ins declare affinity as well as plugins do (ADR-0064 point 4) — otherwise the ranker
 * holds five unlabelled candidates and any labelled plugin wins every track.
 *
 * These are a starting guess, as the ADR says the weights are: they describe what each scene was
 * built to do, and there is no listening data to tune them against yet.
 *
 * **`instrumentalness` and `speechiness` are deliberately not used.** They would be the obvious
 * signal for the two lyric visualizers, and they are not trustworthy: the detector finds *speech*,
 * not singing, so an instrumental track and a sung one are not reliably separated. The `vocal/choir`
 * tag comes from CLAP and is the better proxy for "has someone singing on it".
 */

registerVisualizer(
  {
    id: 'reactive-terrain',
    name: 'Reactive Terrain',
    description: 'Neon wireframe landscape driven by the spectrum, flashing on every beat',
    usesMetadata: true,
    // Spectrum-driven and beat-flashing: it has the most to work with on dense, energetic music.
    affinity: {
      tags: ['electronic', 'energetic', 'synthesizer', 'dense'],
      ranges: [{ feature: 'energy', minimum: 0.4 }],
    },
  },
  lazy(() => import('./ReactiveTerrain'))
);
registerVisualizer(
  {
    id: 'beat-tiles',
    name: 'Beat Tiles',
    description: 'Album cover split into tiles that pop to the beat',
    usesMetadata: true,
    // Every tile moves on a beat, so a track without a clear one leaves the artwork sitting still.
    affinity: {
      tags: ['danceable', 'drums', 'funk', 'hip-hop'],
      ranges: [{ feature: 'danceability', minimum: 0.5 }],
    },
  },
  lazy(() => import('./BeatTiles'))
);
registerVisualizer(
  {
    id: 'lyrics',
    name: 'Lyrics',
    description: 'Scrolling synced lyrics over a drifting field of the song\'s words',
    usesMetadata: true,
    // Nothing to scroll without words. Whether synced lyrics exist is not in the analysis, so the
    // tag is the closest available signal.
    affinity: { tags: ['vocal/choir'], ranges: [] },
  },
  lazy(() => import('./ScrollingLyrics'))
);
registerVisualizer(
  {
    id: 'music-video',
    name: 'Music Video',
    description: 'Search and play synced music videos from YouTube',
    usesMetadata: false,
    // **Deliberately undeclared.** This one plays a video instead of drawing the audio, so no
    // property of the analysis makes it more or less apt — it is a different way of watching, not a
    // scene that suits some music. Declaring nothing scores neutral, which is the honest answer,
    // and is why "no affinity" is neutral rather than last.
  },
  lazy(() => import('./MusicVideo'))
);
// The word field on its own, without the lyric column and vignette `ScrollingLyrics` layers over
// it. Same `LyricWordField` scene, so the two cannot drift apart.
registerVisualizer(
  {
    id: 'lyric-storm',
    name: 'Lyric Storm',
    description: 'The song\'s own words drifting through a dark 3D space, reacting to the music',
    usesMetadata: true,
    affinity: {
      tags: ['vocal/choir', 'dreamy', 'dark', 'ambient'],
      ranges: [{ feature: 'energy', maximum: 0.7 }],
    },
  },
  lazy(() => import('./LyricStorm'))
);
