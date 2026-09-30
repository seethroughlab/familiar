/**
 * The server's own state — health, workers, provider health, background jobs — through the
 * generated client (ADR-0129).
 *
 * Moved here from hand-written wrappers in `admin.ts` while building the Overview (ADR-0126),
 * because the hand-written `WorkerStatus` had no `phase_queues`: the server had been sending the
 * per-phase analysis backlog for months and the TypeScript did not know. Every type below **is**
 * the schema's type; a field the server adds appears on the next `pnpm generate:api`.
 */

import {
  systemDiscoverySourceHealth,
  systemGetBackgroundJobs,
  systemGetWorkerStatus,
  systemSystemHealthCheck,
  type BackgroundJob as WireBackgroundJob,
  type BackgroundJobsResponse as WireBackgroundJobsResponse,
  type DiscoveryHealthResponse,
  type DiscoverySourceHealthResponse,
  type PhaseQueue as WirePhaseQueue,
  type ServiceStatus as WireServiceStatus,
  type SystemHealth as WireSystemHealth,
  type WorkerStatus as WireWorkerStatus,
} from '@familiar/api-client';

export type SystemHealth = WireSystemHealth;
export type ServiceStatus = WireServiceStatus;
export type WorkerStatus = WireWorkerStatus;
export type PhaseQueue = WirePhaseQueue;
export type DiscoveryHealth = DiscoveryHealthResponse;
export type DiscoverySourceHealth = DiscoverySourceHealthResponse;
export type BackgroundJob = WireBackgroundJob;
export type BackgroundJobsResponse = WireBackgroundJobsResponse;

export const systemApi = {
  /** Service-by-service health: library path, database, Redis, background work, analysis. */
  health: async (): Promise<SystemHealth> => {
    const { data } = await systemSystemHealthCheck({ throwOnError: true });
    return data;
  },

  /** Workers, queues, overall analysis progress and the per-phase backlog. */
  workers: async (): Promise<WorkerStatus> => {
    const { data } = await systemGetWorkerStatus({ throwOnError: true });
    return data;
  },

  /** Whether each discovery provider is actually working (ADR-0099 point 6). */
  discoverySources: async (): Promise<DiscoveryHealth> => {
    const { data } = await systemDiscoverySourceHealth({ throwOnError: true });
    return data;
  },

  /** Jobs in flight: library sync, artwork fetch, S3 backup. */
  jobs: async (): Promise<BackgroundJobsResponse> => {
    const { data } = await systemGetBackgroundJobs({ throwOnError: true });
    return data;
  },
};
