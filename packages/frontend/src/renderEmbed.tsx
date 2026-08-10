import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import { initApiOrigin, initServerToken, registerProfileProvider } from './api/base';
import { profileFromURL } from './services/embedBridge';
import { EmbedDiscover } from './components/Embed/EmbedDiscover';


/**
 * Boots the embedded surface (ADR-0017).
 *
 * The sibling of `renderApp`, and deliberately not a variant of it. `App.tsx` is a router with a
 * shell, a transport, a profile selector and thirteen routes; this renders one screen with the
 * providers that screen needs and nothing else.
 *
 * **The point is what it does not mount.** ADR-0017 rejects "the full web app with its chrome
 * hidden" because hiding is not preventing — `useAudioEngine` mounts with the player and constructs
 * an engine whether or not anyone can see it. Reaching that conclusion required a separate entry
 * point, and this is the shared half of it; the platform half registers the null engine before
 * calling this.
 *
 * A `BrowserRouter` is here despite there being nowhere to navigate: `DiscoverBrowser` calls
 * `useNavigate`, and several cards below it use `Link`. Without a router in the tree those throw. It
 * is a real router over a surface with one route, which is cheaper than teasing routing out of a
 * 2,943-line surface that ADR-0016 embedded precisely to avoid maintaining twice.
 */
export function renderEmbed(options?: { onReady?: () => void }): void {
  const profileId = profileFromURL();
  registerProfileProvider({
    getSelectedProfileId: async () => profileId,
    // Nothing to clear: this surface never selected a profile, it was told one. Clearing storage it
    // does not read would be a no-op dressed up as an action.
    clearSelectedProfile: async () => {},
  });


  // Its own client, with the app's defaults. The embedded page is a separate document with a
  // separate cache; nothing is shared with a browser tab that happens to have the app open.
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 1000 * 60 * 5,
        retry: 1,
      },
    },
  });

  // The token too (ADR-0045) — the embedded surface calls the same API the app does.
  Promise.all([initApiOrigin(), initServerToken()]).then(() => {
    options?.onReady?.();
    createRoot(document.getElementById('root')!).render(
      <StrictMode>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <EmbedDiscover />
          </BrowserRouter>
        </QueryClientProvider>
      </StrictMode>,
    );
  });
}
