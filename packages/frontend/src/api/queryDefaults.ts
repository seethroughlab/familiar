/** Shared staleTime tiers for React Query. */
export const STALE_TIME = {
  /** 30s — fast-changing data: alphabet index, search facets */
  SHORT: 30_000,
  /** 1min — moderately stable: sidebar counts, artist detail, favorites */
  MEDIUM: 60_000,
  /** 5min — stable data: scrobbling status, discover browser */
  LONG: 5 * 60_000,
  /** 10min — very stable: playlist detail tracks */
  EXTRA_LONG: 10 * 60_000,
  /** 30min — near-static: discover suggestions (server caches 4h) */
  STATIC: 30 * 60_000,
} as const;

/** Returns `false` when offline (disabling retries), otherwise the specified count. */
export function offlineAwareRetry(isOffline: boolean, retries = 3): number | false {
  return isOffline ? false : retries;
}
