import '@familiar/frontend/src/index.css';
import { registerEngineFactory } from '@familiar/frontend/src/audio/createEngine';
import { registerPlaybackInterceptor } from '@familiar/frontend/src/audio/playbackInterceptor';
import { postPlayIntent } from '@familiar/frontend/src/services/embedBridge';
import { renderEmbed } from '@familiar/frontend/src/renderEmbed';
import { NullAudioEngine } from './NullAudioEngine';

/**
 * The embedded surface's entry point (ADR-0017 point 1).
 *
 * A second entry beside `main.tsx`, not a mode of it. The decision rests on this file being the
 * only thing that boots the *Discover* surface: it registers an engine that cannot make sound, so a
 * play path the bridge fails to intercept is inert rather than a second `WebAudioEngine` competing
 * with the native player for the audio session.
 *
 * It used to say "the only thing that boots the embedded page", which stopped being true when
 * `visualizer.tsx` arrived (ADR-0033). That surface makes the same guarantee the same way — a
 * `NullAudioEngine`, so nothing can construct an `AudioContext` — but declares
 * `visualizer: true`, because `isVisualizerAvailable()` reads the registration and a surface
 * declaring `false` would draw album art forever. The guarantee lives in the omitted `getAnalyser`,
 * not in the flag.
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

// Every play path in the app converges on the queue store, so this is where the surface hands
// playback to the native player — not at a prop.
//
// The prop wiring in `EmbedDiscover` was not enough and this is the record of why:
// `DiscoverTrackList` never calls `onPlayTrack`, it calls `setQueueByTrackId`. Pressing a track in
// "Unheard in Your Library" therefore posted no intent, set a local queue, and handed it to the
// null engine — which correctly made no sound, and left the row spinning forever waiting for a load
// that would never report. Silence was right; the spinner was the bug.
registerPlaybackInterceptor(({ tracks, startingAt }) =>
    postPlayIntent({ trackIds: tracks.map((t) => t.id), startingAt })
);

renderEmbed();
