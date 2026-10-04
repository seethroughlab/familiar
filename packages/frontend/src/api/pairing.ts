/**
 * Pairing a device with this server (ADR-0134), through the generated client (ADR-0129).
 *
 * A pairing link is `familiar://pair?id=…&name=…&host=…&port=…&token=…`. The server supplies
 * everything but the host, because only this page knows how the server is being reached: the host
 * it was loaded from is the one a phone on the same network, or tailnet, can also use. The exception
 * is loopback. A page opened on the server's own machine at `127.0.0.1` falls back to the server's
 * LAN addresses, since a phone cannot reach `127.0.0.1`.
 *
 * **The scheme travels too, as `scheme=https`, and only when it is https.** A NAS reached over
 * Tailscale is usually `https://host:8443`, served by `tailscale serve`, and that port speaks
 * nothing else; the app built every paired address as `http://`, so a code scanned from that page
 * pointed the phone at a port that could not answer it. `http` stays implicit, so every link an
 * older app can already read is byte-for-byte what it was.
 */

import {
  authGetPairing,
  authGetToken,
  authIssueToken,
  type PairingInfo,
  type TokenStatus,
} from '@familiar/api-client';

export type { PairingInfo, TokenStatus };

const LOOPBACK = new Set(['localhost', '127.0.0.1', '::1', '[::1]']);

export function isLoopbackHost(hostname: string): boolean {
  return LOOPBACK.has(hostname) || hostname.startsWith('127.');
}

export type PairingTarget = { host: string; port: number; scheme: 'http' | 'https' };

/** Where a phone should connect, given where this page was loaded from. `null` if nowhere works. */
export function pairingHost(
  info: Pick<PairingInfo, 'addresses' | 'port'>,
  location: { hostname: string; port: string; protocol: string },
): PairingTarget | null {
  const secure = location.protocol === 'https:';
  const pagePort = location.port ? Number(location.port) : secure ? 443 : 80;
  if (!isLoopbackHost(location.hostname)) {
    return { host: location.hostname, port: pagePort, scheme: secure ? 'https' : 'http' };
  }
  // The server's own LAN listener is plain http (ADR-0134 point 2), whatever this page used.
  const lan = info.addresses[0];
  if (!lan) return null;
  return { host: lan, port: info.port ?? pagePort, scheme: 'http' };
}

export function buildPairingLink(
  info: Pick<PairingInfo, 'server_id' | 'server_name' | 'token'>,
  target: { host: string; port: number; scheme?: 'http' | 'https' },
): string {
  const params = new URLSearchParams({
    id: info.server_id,
    name: info.server_name,
    host: target.host,
    port: String(target.port),
    token: info.token,
  });
  if (target.scheme === 'https') params.set('scheme', 'https');
  return `familiar://pair?${params.toString()}`;
}

export const pairingApi = {
  tokenStatus: async (): Promise<TokenStatus> => {
    const { data } = await authGetToken({ throwOnError: true });
    return data;
  },
  /** Mint a token. The first one needs nothing; replacing one needs the current one (sent by base.ts). */
  issueToken: async (): Promise<string> => {
    const { data } = await authIssueToken({ throwOnError: true });
    return data.token;
  },
  pairing: async (): Promise<PairingInfo> => {
    const { data } = await authGetPairing({ throwOnError: true });
    return data;
  },
};
