import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { chatApi } from '../api/chat';
import { useUIStore } from '../stores/uiStore';

/**
 * Ask the server whether it has a working LLM provider, and hide chat everywhere if it does not.
 *
 * **The endpoint was built for this and had never been called.** `GET /chat/status` says in its own
 * docstring that it exists "so the frontend can show appropriate warnings before the user tries to
 * chat", and `chatApi.getStatus` had no callers anywhere — so an install with no key configured
 * showed a chat box that failed on send. ADR-0022 point 3 refused that on the native app; this is
 * the same defect on the surface that has shipped it all along.
 *
 * It reports the *active* provider, so choosing OpenAI without OpenAI credentials is unconfigured
 * even with `ANTHROPIC_API_KEY` set.
 *
 * **A failed request deliberately leaves the flag alone.** An unreachable server is not an
 * unconfigured provider, and treating the two the same would make chat vanish whenever the network
 * hiccuped. The cost is the opposite flicker — chat is present until a definite "no" arrives — which
 * only affects installs that have no provider at all, and only for one request.
 */
export function useChatAvailability(): void {
  const setChatSurfaceAvailable = useUIStore((s) => s.setChatSurfaceAvailable);

  const { data } = useQuery({
    queryKey: ['chat', 'status'],
    queryFn: () => chatApi.getStatus(),
    // Configuring a key happens on the admin page, in another tab. Long enough not to ask on every
    // mount, short enough that turning chat on does not need a reload to be noticed.
    staleTime: 1000 * 60 * 5,
    retry: 1,
  });

  useEffect(() => {
    if (data) setChatSurfaceAvailable(data.configured);
  }, [data, setChatSurfaceAvailable]);
}
