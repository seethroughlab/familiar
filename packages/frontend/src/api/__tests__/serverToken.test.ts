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
   * Note on what protects what. The "don't clear the profile" property holds *by construction* —
   * the profile branch matches on `re-register` / `Invalid profile`, and the token 401's detail
   * contains neither — not because of the early return in the interceptor. Removing that return
   * leaves this suite green, which was checked. So the assertion below is about the behaviour the
   * code actually adds: announcing that a token is needed. The profile case is asserted alongside
   * it to pin the string coupling, since the two details are matched by substring and a reworded
   * server message would silently reroute one into the other.
   */
  it('announces that a token is required', async () => {
    const onNeeded = vi.fn();
    window.addEventListener('server-token-required', onNeeded);

    const handlers = (api.interceptors.response as unknown as {
      handlers: { rejected: (e: unknown) => unknown }[];
    }).handlers;

    const tokenError = {
      response: {
        status: 401,
        data: { detail: 'Send the server token in the X-Familiar-Token header.' },
      },
    };

    for (const h of handlers) {
      if (h?.rejected) {
        await h.rejected(tokenError).catch(() => {});
      }
    }

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

    const handlers = (api.interceptors.response as unknown as {
      handlers: { rejected: (e: unknown) => unknown }[];
    }).handlers;

    const tokenError = {
      response: {
        status: 401,
        data: { detail: 'Send the server token in the X-Familiar-Token header.' },
      },
    };

    for (const h of handlers) {
      if (h?.rejected) {
        await h.rejected(tokenError).catch(() => {});
      }
    }

    expect(clearSelectedProfile).not.toHaveBeenCalled();
  });

  it('still clears the profile when the profile is what failed', async () => {
    const clearSelectedProfile = vi.fn(async () => {});
    const { registerProfileProvider } = await import('../base');
    registerProfileProvider({
      getSelectedProfileId: async () => 'profile-1',
      clearSelectedProfile,
    });

    const handlers = (api.interceptors.response as unknown as {
      handlers: { rejected: (e: unknown) => unknown }[];
    }).handlers;

    const profileError = {
      response: {
        status: 401,
        data: { detail: 'Invalid profile ID - please re-register' },
      },
    };

    for (const h of handlers) {
      if (h?.rejected) {
        await h.rejected(profileError).catch(() => {});
      }
    }

    expect(clearSelectedProfile).toHaveBeenCalled();
  });
});
