import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useChatAvailability } from '../useChatAvailability';
import { useUIStore } from '../../stores/uiStore';
import { chatApi } from '../../api/chat';

vi.mock('../../api/chat', () => ({ chatApi: { getStatus: vi.fn() } }));

/**
 * `GET /chat/status` exists so the frontend can avoid showing a chat box that fails on send — and
 * had no callers anywhere in the web app until this hook. ADR-0022 point 3 refused that on the
 * native app; these pin the same rule here.
 */
describe('useChatAvailability', () => {
  const wrapper = ({ children }: { children: ReactNode }) => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };

  beforeEach(() => {
    vi.clearAllMocks();
    useUIStore.setState({ chatSurfaceAvailable: true });
  });

  it('hides chat when the server has no provider configured', async () => {
    vi.mocked(chatApi.getStatus).mockResolvedValue({ configured: false, provider: null });

    renderHook(() => useChatAvailability(), { wrapper });

    await waitFor(() => expect(useUIStore.getState().chatSurfaceAvailable).toBe(false));
  });

  it('leaves chat available when a provider is configured', async () => {
    vi.mocked(chatApi.getStatus).mockResolvedValue({ configured: true, provider: 'anthropic' });

    renderHook(() => useChatAvailability(), { wrapper });

    await waitFor(() => expect(chatApi.getStatus).toHaveBeenCalled());
    expect(useUIStore.getState().chatSurfaceAvailable).toBe(true);
  });

  /**
   * An unreachable server is not an unconfigured provider. Treating the two the same would make
   * chat vanish whenever the network hiccuped.
   */
  it('leaves the flag alone when the request fails', async () => {
    vi.mocked(chatApi.getStatus).mockRejectedValue(new Error('offline'));

    renderHook(() => useChatAvailability(), { wrapper });

    await waitFor(() => expect(chatApi.getStatus).toHaveBeenCalled());
    expect(useUIStore.getState().chatSurfaceAvailable).toBe(true);
  });
});
