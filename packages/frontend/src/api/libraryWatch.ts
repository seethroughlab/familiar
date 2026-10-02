/**
 * The library watch (ADR-0142): whether new music is noticed when its folder goes quiet, or only at
 * the next sync. On the generated client (ADR-0129).
 */
import { ingestGetWatchStatus, type WatchStatusResponse } from '@familiar/api-client';

export type { WatchStatusResponse as WatchStatus };

export const libraryWatchApi = {
  status: async (): Promise<WatchStatusResponse> => {
    const { data } = await ingestGetWatchStatus({ throwOnError: true });
    return data;
  },
};
