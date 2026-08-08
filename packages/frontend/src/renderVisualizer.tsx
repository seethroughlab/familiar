import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { initApiOrigin, registerProfileProvider } from './api/base';
import { profileFromURL } from './services/embedBridge';
import { EmbedVisualizer } from './components/Embed/EmbedVisualizer';
import { useUIStore } from './stores/uiStore';

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
  const profileId = profileFromURL();
  registerProfileProvider({
    getSelectedProfileId: async () => profileId,
    // Same as the Discover surface: it was told a profile, it never chose one, so there is nothing
    // to clear.
    clearSelectedProfile: async () => {},
  });

  // No shell, so nothing renders a chat panel. Declared rather than inferred, so the affordances
  // that lead to chat stand down instead of each one learning it might be embedded.
  useUIStore.getState().setChatSurfaceAvailable(false);

  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 1000 * 60 * 5,
        retry: 1,
      },
    },
  });

  initApiOrigin().then(() => {
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
