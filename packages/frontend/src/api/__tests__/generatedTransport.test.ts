/**
 * The generated client rides the shared transport (ADR-0129 point 7).
 *
 * A generated operation and a hand-written wrapper must leave the browser with the same origin,
 * server token and profile header. This drives `libraryWatchApi.status` — the first operation on
 * the generated path was `soulseekApi.status`, gone with ADR-0154 — and reads the request the way
 * the server would.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import type { AxiosRequestConfig } from 'axios';
import { client } from '@familiar/api-client';
import { registerProfileProvider, setServerToken } from '../base';
import { libraryWatchApi } from '../libraryWatch';

/** Capture the request the generated client's instance would send, and answer it. */
function captureNextRequest(answer: unknown): { config: AxiosRequestConfig | null } {
  const seen: { config: AxiosRequestConfig | null } = { config: null };
  const instance = client.getConfig().axios!;
  instance.defaults.adapter = async (config) => {
    seen.config = config;
    return { data: answer, status: 200, statusText: 'OK', headers: {}, config };
  };
  return seen;
}

describe('a generated operation on the shared transport', () => {
  beforeEach(async () => {
    localStorage.clear();
    await setServerToken('');
    registerProfileProvider({
      getSelectedProfileId: async () => null,
      clearSelectedProfile: async () => {},
    });
  });

  it('hits the full API path against the same origin as the wrappers', async () => {
    const seen = captureNextRequest({ watching: false });
    await libraryWatchApi.status();
    expect(seen.config?.baseURL).toBe('');
    expect(seen.config?.url).toBe('/api/v1/library/sync/watch');
    expect(seen.config?.method?.toLowerCase()).toBe('get');
  });

  it('carries the server token and the selected profile without being told', async () => {
    await setServerToken('tok-abc');
    registerProfileProvider({
      getSelectedProfileId: async () => 'profile-1',
      clearSelectedProfile: async () => {},
    });
    const seen = captureNextRequest({ watching: false });
    await libraryWatchApi.status();
    const headers = seen.config?.headers as Record<string, unknown>;
    expect(headers['X-Familiar-Token']).toBe('tok-abc');
    expect(headers['X-Profile-ID']).toBe('profile-1');
  });

  it('returns the wire response as the adapter’s type', async () => {
    const wire = {
      watching: true, roots: ['/music'], pending: 2, last_scan_at: 1761400000, reason: null,
    };
    captureNextRequest(wire);
    const status = await libraryWatchApi.status();
    expect(status).toEqual(wire);
  });

  it('a coded 401 through the generated client reaches the same interceptor', async () => {
    const clearSelectedProfile = vi.fn(async () => {});
    registerProfileProvider({ getSelectedProfileId: async () => 'p', clearSelectedProfile });
    const instance = client.getConfig().axios!;
    instance.defaults.adapter = async (config) => {
      const { AxiosError } = await import('axios');
      throw new AxiosError('Unauthorized', 'ERR_BAD_REQUEST', config, null, {
        data: { error: true, status_code: 401, message: '…', code: 'INVALID_PROFILE' },
        status: 401, statusText: 'Unauthorized', headers: {}, config,
      });
    };
    await expect(libraryWatchApi.status()).rejects.toBeTruthy();
    expect(clearSelectedProfile).toHaveBeenCalled();
  });
});
