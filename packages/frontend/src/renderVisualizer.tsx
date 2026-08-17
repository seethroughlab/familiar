import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { initApiOrigin, registerProfileProvider, setApiOrigin } from './api/base';
import { profileFromURL } from './services/embedBridge';
import { EmbedVisualizer } from './components/Embed/EmbedVisualizer';
import { installVisualizerSink } from './services/visualizerSink';
import { useVisualizerStore } from './stores/visualizerStore';
import { loadVisualizerPlugins } from './services/visualizerPluginHost';
import { getVisualizers } from './components/Visualizer/types';
// Side-effect import: registers the compile-time visualizers. **Explicit here, and before the
// plugin loader runs**, because the loader needs their ids to refuse a drop-in plugin that would
// otherwise overwrite one (ADR-0034). `AudioVisualizer` imports the same module, but that happens
// at mount — far too late to be the thing the loader consults.
import './components/Visualizer/visualizers';

/**
 * Boots the embedded visualizer surface (ADR-0033).
 *
 * The sibling of `renderEmbed`, and thinner still. That one mounts a browsable Discover screen and
 * needs a `BrowserRouter` because its cards use `Link`; this mounts one component that draws and
 * has nowhere to go, so there is no router at all. If a visualizer ever wants to navigate it should
 * post an intent, not push a route — the native app owns navigation (ADR-0020).
 *
 * The `QueryClient` is here for artwork and lyrics, which the page fetches itself (ADR-0033 point
 * 8) rather than having them pushed down the channel. A channel that carries everything has no
 * shape, and lyrics are a request the page can make perfectly well on its own.
 */
export function renderVisualizer(options?: { onReady?: () => void }): void {
  // **First, before anything async.** The host probes for the sink as soon as the document finishes
  // loading, which is well before `initApiOrigin` resolves or React mounts — installing it any
  // later loses that race and the host reports a page that is not listening. It also means frames
  // arriving during boot land in the buffers instead of being dropped.
  installVisualizerSink();

  const profileId = profileFromURL();

  // **The host tells this page where the server is.**
  //
  // Read out of the app bundle over a custom URL scheme (ADR-0034 point 4), this page has no server
  // in its own location to infer one from. `initApiOrigin` derives the origin from where the
  // document was served, which is right for the web app and for the embedded Discover page — both
  // come from the server — and yields an empty string here. Origin-relative URLs would then resolve
  // against the custom scheme and fetch nothing, so artwork would silently never load.
  //
  // `setApiOrigin` caches to localStorage, which the custom scheme has because it is a real origin
  // (a `file://` or `loadHTMLString` page would not). This page is now its only caller — the
  // Connect-to-Server screen that used to share it went with the Capacitor app (ADR-0001 point 6).
  const params = new URLSearchParams(window.location.search);

  // **Which visualizer to draw, chosen by the host.**
  //
  // The page persists a choice of its own to `localStorage`, which is right for the web app where
  // the picker lives beside the visualizer. Embedded, the picker is a native menu, so the app is
  // the source of truth and says so on the URL — otherwise the two would each remember a different
  // answer and whichever wrote last would win.
  const visualizer = params.get('visualizer');
  if (visualizer) useVisualizerStore.getState().setVisualizerId(visualizer);

  const api = params.get('api');
  registerProfileProvider({
    getSelectedProfileId: async () => profileId,
    // Same as the Discover surface: it was told a profile, it never chose one, so there is nothing
    // to clear.
    clearSelectedProfile: async () => {},
  });


  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 1000 * 60 * 5,
        retry: 1,
      },
    },
  });

  // Only when the host did not say — `initApiOrigin` would otherwise overwrite an explicit origin
  // with an origin-relative empty string.
  const ready = api ? setApiOrigin(api) : initApiOrigin();

  // **Drop-in visualizers, before the first render** (ADR-0034). They have to be in the registry
  // by the time `AudioVisualizer` looks up the chosen id, or a plugin the host was told to draw
  // would fall back to the default on every launch and only appear after some later re-render.
  //
  // `catch` rather than trust: `loadVisualizerPlugins` is written never to reject, and if that ever
  // stops being true the cost is a page that never mounts — a black rectangle with no error, which
  // is the failure this surface produces over and over. A plugin problem must not be able to take
  // the visualizer down with it.
  const plugins = loadVisualizerPlugins(getVisualizers().map((v) => v.metadata.id)).catch(() => {});

  Promise.all([ready, plugins]).then(() => {
    options?.onReady?.();
    createRoot(document.getElementById('root')!).render(
      <StrictMode>
        <QueryClientProvider client={queryClient}>
          <EmbedVisualizer />
        </QueryClientProvider>
      </StrictMode>,
    );
  });
}
