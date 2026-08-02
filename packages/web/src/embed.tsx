import '@familiar/frontend/src/index.css';
import { registerEngineFactory } from '@familiar/frontend/src/player/audio/createEngine';
import { renderEmbed } from '@familiar/frontend/src/renderEmbed';
import { NullAudioEngine } from './NullAudioEngine';

/**
 * The embedded surface's entry point (ADR-0017 point 1).
 *
 * A second entry beside `main.tsx`, not a mode of it. The whole decision rests on this file being
 * the only thing that boots the embedded page: it registers an engine that cannot make sound, so a
 * play path the bridge fails to intercept is inert rather than a second `WebAudioEngine` competing
 * with the native player for the audio session.
 *
 * Registering *nothing* was the obvious alternative and is rejected by ADR-0017 point 4:
 * `createEngine()` throws when no factory is registered, which would turn a missed play intent into
 * a crash inside a web view inside a native app.
 *
 * No service worker is registered here. `main.tsx` reloads the page when a new one takes control,
 * which inside a native web view would be a screen refreshing itself for reasons no one watching
 * could see.
 */
registerEngineFactory(() => new NullAudioEngine(), {
  crossfade: false,
  visualizer: false,
  effects: 'none',
});

renderEmbed();
