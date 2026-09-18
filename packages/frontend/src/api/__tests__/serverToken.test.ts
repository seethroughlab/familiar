import { describe, it, expect, beforeEach, vi } from 'vitest';
import api, {
  getServerToken,
  initServerToken,
  setServerToken,
} from '../base';

/**
 * The server token (ADR-0045).
 *
 * What is worth testing here is not that a header gets set — it is the three ways this quietly
 * stops working:
 *
 * 1. The token is read from a module-level cache that `initServerToken` fills. If boot renders
 *    before that resolves, the opening requests go out unauthenticated and a correctly configured
 *    server answers 401, which reads as "the server is broken".
 * 2. It must survive a reload. A credential that has to be re-pasted every visit will be turned off.
 * 3. A token 401 must not be mistaken for a profile 401. Both are 401; clearing the selected
 *    profile in response to a token failure would log the listener out of something that was never
 *    the problem, and the profile selector would then 401 too.
 */

function requestConfig(token: string) {
  // Run the request interceptors the way axios does, over a minimal config.
  const config: { headers: Record<string, string> } = { headers: {} };
  void token;
  return config;
}

describe('server token', () => {
  beforeEach(async () => {
    localStorage.clear();
    await setServerToken('');
  });

  it('persists across a reload', async () => {
    await setServerToken('tok-abc');
    expect(localStorage.getItem('familiar_server_token')).toBe('tok-abc');

    // Simulate a fresh boot: the in-memory cache is gone, storage is not.
    await setServerToken('');
    localStorage.setItem('familiar_server_token', 'tok-abc');
    await initServerToken();

    expect(getServerToken()).toBe('tok-abc');
  });

  // Two cases covering the Capacitor Preferences store used to live here — a fallback read and a
  // mirrored write. Both went with `registerPreferencesProvider`: the app that would have supplied
  // one was deleted on 2026-08-11 (ADR-0001 point 6), and nothing ever registered a provider, so
  // they asserted a path no build could take. localStorage is now the only store.
  it('clears from storage when set to empty', async () => {
    await setServerToken('tok-xyz');
    expect(localStorage.getItem('familiar_server_token')).toBe('tok-xyz');

    await setServerToken('');

    expect(getServerToken()).toBe('');
    expect(localStorage.getItem('familiar_server_token')).toBeNull();
  });

  it('clears on an empty string rather than storing one', async () => {
    await setServerToken('tok-abc');
    await setServerToken('');

    expect(getServerToken()).toBe('');
    expect(localStorage.getItem('familiar_server_token')).toBeNull();
  });

  it('trims a pasted token', async () => {
    // Copying from a terminal or an admin page routinely brings whitespace with it, and a token is
    // opaque enough that a trailing newline is invisible in the field.
    await setServerToken('  tok-abc\n');
    expect(getServerToken()).toBe('tok-abc');
  });

  it('attaches the token to outgoing requests', async () => {
    await setServerToken('tok-abc');

    const config = requestConfig('tok-abc');
    // Exercise the real interceptor chain rather than reimplementing it.
    const handlers = (api.interceptors.request as unknown as {
      handlers: { fulfilled: (c: unknown) => unknown }[];
    }).handlers;
    let result: { headers: Record<string, string> } = config;
    for (const h of handlers) {
      if (h?.fulfilled) result = (await h.fulfilled(result)) as typeof config;
    }

    expect(result.headers['X-Familiar-Token']).toBe('tok-abc');
  });

  it('sends no token header when none is configured', async () => {
    await setServerToken('');

    const handlers = (api.interceptors.request as unknown as {
      handlers: { fulfilled: (c: unknown) => unknown }[];
    }).handlers;
    let result: { headers: Record<string, string> } = { headers: {} };
    for (const h of handlers) {
      if (h?.fulfilled) result = (await h.fulfilled(result)) as typeof result;
    }

    expect(result.headers['X-Familiar-Token']).toBeUndefined();
  });
});

describe('a token 401 is not a profile 401', () => {
  /**
   * The envelopes below are the ones the server sends, key for key (ADR-0129 point 6). The
   * previous version of this suite faked `detail` sentences and matched on them — and the real
   * profile 401 carries its sentence in `message` with no `detail` at all, so the suite was green
   * while the profile branch had never once fired in a browser. `code` is the contract now; the
   * prose is deliberately absent from these fixtures so a test cannot pass by matching it.
   */
  type Rejected = { rejected?: (e: unknown) => Promise<unknown> };
  const rejectedHandlers = () =>
    (api.interceptors.response as unknown as { handlers: Rejected[] }).handlers;

  const tokenError = {
    response: {
      status: 401,
      data: { error: true, status_code: 401, message: '…', code: 'SERVER_TOKEN_REQUIRED' },
    },
  };
  const profileError = {
    response: {
      status: 401,
      data: { error: true, status_code: 401, message: '…', code: 'INVALID_PROFILE' },
    },
  };

  async function reject(error: unknown) {
    for (const h of rejectedHandlers()) {
      if (h?.rejected) {
        await h.rejected(error).catch(() => {});
      }
    }
  }

  it('announces that a token is required', async () => {
    const onNeeded = vi.fn();
    window.addEventListener('server-token-required', onNeeded);
    await reject(tokenError);
    window.removeEventListener('server-token-required', onNeeded);
    expect(onNeeded).toHaveBeenCalled();
  });

  it('does not clear the selected profile when the token is what failed', async () => {
    const clearSelectedProfile = vi.fn(async () => {});
    const { registerProfileProvider } = await import('../base');
    registerProfileProvider({
      getSelectedProfileId: async () => 'profile-1',
      clearSelectedProfile,
    });
    await reject(tokenError);
    expect(clearSelectedProfile).not.toHaveBeenCalled();
  });

  it('clears the profile when the profile is what failed', async () => {
    const clearSelectedProfile = vi.fn(async () => {});
    const { registerProfileProvider } = await import('../base');
    registerProfileProvider({
      getSelectedProfileId: async () => 'profile-1',
      clearSelectedProfile,
    });
    await reject(profileError);
    expect(clearSelectedProfile).toHaveBeenCalled();
  });

  it('a 401 without a code does neither — prose is not a signal', async () => {
    const clearSelectedProfile = vi.fn(async () => {});
    const onNeeded = vi.fn();
    const { registerProfileProvider } = await import('../base');
    registerProfileProvider({ getSelectedProfileId: async () => 'p', clearSelectedProfile });
    window.addEventListener('server-token-required', onNeeded);
    await reject({
      response: {
        status: 401,
        data: {
          error: true,
          status_code: 401,
          message: 'Invalid profile ID - please re-register',
          detail: 'Send the server token in the X-Familiar-Token header.',
        },
      },
    });
    window.removeEventListener('server-token-required', onNeeded);
    expect(clearSelectedProfile).not.toHaveBeenCalled();
    expect(onNeeded).not.toHaveBeenCalled();
  });
});
