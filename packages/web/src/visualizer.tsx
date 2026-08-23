import '@familiar/frontend/src/index.css';
import { registerEngineFactory } from '@familiar/frontend/src/audio/createEngine';
import { renderVisualizer } from '@familiar/frontend/src/renderVisualizer';
import { NullAudioEngine } from './NullAudioEngine';

/**
 * The embedded visualizer surface's entry point (ADR-0033).
 *
 * The third entry beside `main.tsx` and `embed.tsx`, and the only one that is *told* things. The
 * Discover surface posts intents and is never told what is playing — ADR-0016 point 5 made that a
 * rule, and a visualizer's entire job is to break it, which is why ADR-0033 amends the point rather
 * than working around it.
 *
 * **`visualizer: true` on an engine that cannot make a sound**, and the combination is deliberate.
 * `isVisualizerAvailable()` reads the *registration*, so a surface declaring `false` would render
 * album art and never a visualizer. What preserves ADR-0017's guarantee is not the flag but the
 * omission: `NullAudioEngine` implements none of the sixteen optional members, so
 * `getAudioAnalyser()` calls `existingEngine()?.getAnalyser?.()` and gets `undefined` — nothing can
 * construct an `AudioContext` here no matter what the capabilities claim.
 *
 * No playback interceptor, unlike `embed.tsx`. This page has no play buttons: it draws what it is
 * sent. If it ever grows one, it needs the interceptor *and* a bridge message, and ADR-0020 point 3
 * sets the bar for that.
 */
registerEngineFactory(
  () =>
    new NullAudioEngine({
      crossfade: false,
      visualizer: true,
      effects: 'none',
    }),
  {
    crossfade: false,
    visualizer: true,
    effects: 'none',
  }
);

renderVisualizer();
