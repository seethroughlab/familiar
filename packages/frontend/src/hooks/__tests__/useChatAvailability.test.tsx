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

/**
 * The failure CI caught and a local run did not: the status answer arrives *after* the first
 * paint, so chat can already be open by the time it turns out to be unavailable. Guarding the
 * panel's render on availability left an open panel with no input in it — a worse state than the
 * one the gate exists to prevent, and the reason four E2E tests timed out looking for a chat box
 * that was on screen but empty.
 */
describe('useChatAvailability when chat is already open', () => {
  const wrapper = ({ children }: { children: ReactNode }) => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };

  it('closes the panel when the answer turns out to be no', async () => {
    useUIStore.setState({ chatSurfaceAvailable: true, rightPanel: 'chat' });
    vi.mocked(chatApi.getStatus).mockResolvedValue({ configured: false, provider: null });

    renderHook(() => useChatAvailability(), { wrapper });

    await waitFor(() => expect(useUIStore.getState().rightPanel).toBeNull());
  });

  it('leaves an open panel alone when a provider is configured', async () => {
    useUIStore.setState({ chatSurfaceAvailable: true, rightPanel: 'chat' });
    vi.mocked(chatApi.getStatus).mockResolvedValue({ configured: true, provider: 'anthropic' });

    renderHook(() => useChatAvailability(), { wrapper });

    await waitFor(() => expect(chatApi.getStatus).toHaveBeenCalled());
    expect(useUIStore.getState().rightPanel).toBe('chat');
  });

  /** The queue must not be closed by a chat answer. */
  it('does not close a different panel', async () => {
    useUIStore.setState({ chatSurfaceAvailable: true, rightPanel: 'queue' });
    vi.mocked(chatApi.getStatus).mockResolvedValue({ configured: false, provider: null });

    renderHook(() => useChatAvailability(), { wrapper });

    await waitFor(() => expect(useUIStore.getState().chatSurfaceAvailable).toBe(false));
    expect(useUIStore.getState().rightPanel).toBe('queue');
  });
});
