import { describe, it, expect, beforeEach } from 'vitest';
import { getServerToken, initServerToken, setServerToken } from '../base';
import { buildPairingLink, pairingHost } from '../pairing';

/** ADR-0134 points 5 and 6: how a device is paired, and how the admin receives a token. */

describe('token handed over in the fragment', () => {
  beforeEach(async () => {
    localStorage.clear();
    await setServerToken('');
    window.history.replaceState(null, '', '/');
  });

  it('is stored, and removed from the address bar', async () => {
    window.history.replaceState(null, '', '/server/access#token=tok-from-the-app');
    await initServerToken();
    expect(getServerToken()).toBe('tok-from-the-app');
    expect(localStorage.getItem('familiar_server_token')).toBe('tok-from-the-app');
    expect(window.location.hash).toBe('');
    expect(window.location.pathname).toBe('/server/access');
  });

  it('keeps any other fragment parameters', async () => {
    window.history.replaceState(null, '', '/#token=t&tab=2');
    await initServerToken();
    expect(window.location.hash).toBe('#tab=2');
  });

  it('leaves a stored token alone when there is none in the fragment', async () => {
    await setServerToken('stored');
    await initServerToken();
    expect(getServerToken()).toBe('stored');
  });
});

describe('pairing link', () => {
  const info = {
    server_id: 'id-1',
    server_name: 'Studio MacBook',
    token: 'tok/+=',
    port: 4400,
    addresses: ['192.168.1.20'],
  };

  it('uses the host this page was loaded from', () => {
    const target = pairingHost(info, { hostname: 'nas.tailnet.ts.net', port: '4400', protocol: 'http:' });
    expect(target).toEqual({ host: 'nas.tailnet.ts.net', port: 4400 });
  });

  it('falls back to a LAN address when the page is on loopback, which a phone cannot reach', () => {
    const target = pairingHost(info, { hostname: '127.0.0.1', port: '4400', protocol: 'http:' });
    expect(target).toEqual({ host: '192.168.1.20', port: 4400 });
  });

  it('has nowhere to point when loopback is all there is', () => {
    expect(pairingHost({ ...info, addresses: [] }, { hostname: 'localhost', port: '4400', protocol: 'http:' })).toBeNull();
  });

  it('encodes every value so a token survives being a URL parameter', () => {
    const link = buildPairingLink(info, { host: '192.168.1.20', port: 4400 });
    expect(link.startsWith('familiar://pair?')).toBe(true);
    const params = new URL(link.replace('familiar://', 'http://x/')).searchParams;
    expect(Object.fromEntries(params)).toEqual({
      id: 'id-1',
      name: 'Studio MacBook',
      host: '192.168.1.20',
      port: '4400',
      token: 'tok/+=',
    });
  });
});
